from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

import httpx

from core.state import CameraState
from drivers.base import CameraCommandError, CameraDriver
from drivers.panasonic_models.registry import resolve_model

LOGGER = logging.getLogger("ptz_control.panasonic")

# --- Iris (#AXI / #GI): normalized 0.0-1.0 <-> 555h-FFFh, linear ---
_IRIS_DATA_MIN = 0x555
_IRIS_DATA_MAX = 0xFFF

# --- Iris F-number (QIF/OIF): Data/10 = F-number over the linear range
# 0Eh(F1.4)-A0h(F16.0); FFh=CLOSE is a separate sentinel, not part of the
# linear formula. The range A1h-FEh (between the F16 anchor and CLOSE) is
# not decoded -- query_f_number() falls back to the raw hex value there.
# Only supported by camera models flagged via SUPPORTS_IRIS_F_NUMBER.
_F_NUMBER_DATA_MIN = 0x0E
_F_NUMBER_DATA_MAX = 0xA0
_F_NUMBER_CLOSE_DATA = 0xFF

# --- Gain (OGU/QGU): Data = 0x08 + db, 0x80 = AGC/Auto. These anchors are
# identical across every documented model; the actual per-camera range/step
# (GAIN_MIN_DB/GAIN_MAX_DB/GAIN_STEP_DB) comes from the resolved model
# module, see _apply_model_catalog().
_GAIN_ZERO_DB_DATA = 0x08
_GAIN_AGC_DATA = 0x80

# --- R/B gain preset (OSL:36/38): 418h(-1000)-800h(0)-BE8h(+1000) -> Data = 0x800 + value ---
_RB_GAIN_CENTER_DATA = 0x800

_ERROR_PREFIXES_CAM = ("ER1:", "ER2:", "ER3:")
_ERROR_PREFIXES_PTZ = ("eR1", "eR2", "eR3")
_ERROR_STATE_PREFIXES = ("rER", "OER")

_REQUEST_TIMEOUT = 1.5  # default timeout, 1 retry

# --- Update notification channel + lens info ---
# Frame layout: 22B reserve, 2B size (big-endian, payload length + 8), 4B
# reserve, payload, 24B reserve. Each notification arrives as its own
# short-lived TCP connection with exactly one frame, not a persistent stream.
_NOTIFY_HEADER_RESERVE = 22
_NOTIFY_SIZE_FIELD_LEN = 2
_NOTIFY_MID_RESERVE = 4
_NOTIFY_HEADER_LEN = _NOTIFY_HEADER_RESERVE + _NOTIFY_SIZE_FIELD_LEN + _NOTIFY_MID_RESERVE
# QSV notifications arrive every 60s as a heartbeat; >90s without one means
# the connection is treated as stale and re-registered (new socket). Any
# notification counts as a heartbeat here, not just QSV.
_NOTIFY_HEARTBEAT_TIMEOUT = 90.0
# The camera only accepts a single registered event-notification client at a
# time -- opening the camera's own web UI in a browser registers itself the
# same way and silently steals the slot. Re-sending the registration (same
# socket, no teardown) on this shorter interval reclaims it regularly instead
# of only recovering after a full silence timeout.
_NOTIFY_REREGISTER_INTERVAL = 30.0


def _parse_notification_payload(frame: bytes) -> str | None:
    """Payload frame is `\\r\\n<command>\\r\\n`, padded with null bytes up to
    the length declared in `size`. Null bytes aren't whitespace for
    `str.strip()`, so `strip("\\x00\\r\\n \\t")` is needed to remove both in
    one pass."""
    if len(frame) < _NOTIFY_HEADER_LEN:
        return None
    size = int.from_bytes(
        frame[_NOTIFY_HEADER_RESERVE : _NOTIFY_HEADER_RESERVE + _NOTIFY_SIZE_FIELD_LEN], "big"
    )
    payload_len = size - 8
    if payload_len < 0 or len(frame) < _NOTIFY_HEADER_LEN + payload_len:
        return None
    payload = frame[_NOTIFY_HEADER_LEN : _NOTIFY_HEADER_LEN + payload_len]
    return payload.decode("ascii", errors="replace").strip("\x00\r\n \t")


def _parse_lens_info_iris(body: str) -> float | None:
    """`lPI[ZZZ][FFF][III]` (zoom/focus/iris, 3 hex digits each) -- only
    iris (the last 3 digits) is used, zoom/focus are ignored."""
    if not body.startswith("lPI") or len(body) != 12:
        return None
    try:
        data = int(body[9:12], 16)
    except ValueError:
        return None
    return _data_to_iris(data)


def _iris_to_data(value: float) -> int:
    return _IRIS_DATA_MIN + round(value * (_IRIS_DATA_MAX - _IRIS_DATA_MIN))


def _data_to_iris(data: int) -> float:
    return (data - _IRIS_DATA_MIN) / (_IRIS_DATA_MAX - _IRIS_DATA_MIN)


def _decode_f_number(data: int) -> str | None:
    """QIF data -> F-number label. `None` if `data` is outside the confirmed
    range -- callers fall back to the raw hex value instead."""
    if data == _F_NUMBER_CLOSE_DATA:
        return "CLOSE"
    if _F_NUMBER_DATA_MIN <= data <= _F_NUMBER_DATA_MAX:
        return f"F{data / 10:.1f}"
    return None


def _extract_value(body: str) -> str | None:
    """Value after the last ':' -- the consistent response pattern for
    every command (e.g. 'OGU:08' -> '08', 'OID:AW-UE160' -> 'AW-UE160')."""
    if not body or ":" not in body:
        return None
    value = body.rsplit(":", 1)[-1].strip()
    return value or None


def _decode_gain_data(data: int) -> tuple[int | None, bool]:
    """Gain encoding (Data = 0x08 + db, 0x80 = Auto/AGC), shared between
    `_query_gain_state()` and the update-notification handling since both
    decode the same `OGU:[Data]` encoding. Returns (dB value or `None` if
    Auto, is_auto)."""
    if data == _GAIN_AGC_DATA:
        return None, True
    return data - _GAIN_ZERO_DB_DATA, False


def _match_toggle_feature(body: str, features: dict[str, dict]) -> list[tuple[str, bool]]:
    """Matches an update-notification payload (the same command string as
    sent) against toggle features in `BUTTON_FEATURES` by comparing `body`
    to each known `on`/`off` command.

    A command can be shared by more than one feature (e.g. AW-UE160's
    `knee_manual`/`knee_auto` both send `OSL:45:1` as part of their "on"
    sequence, since a single physical command arms knee mode before a
    second command picks manual/auto). If `body` matches more than one
    feature's "on" list, which one actually turned on can't be determined
    from this command alone, so no "on" event fires for it -- the other,
    distinguishing command in the sequence fires on its own. A shared "off"
    match is unambiguous (every feature that maps to it really did turn
    off) and fires for all of them."""
    on_matches: list[str] = []
    off_matches: list[str] = []
    for key, feature in features.items():
        if feature.get("kind") != "toggle":
            continue
        on_commands = feature.get("on")
        if on_commands is not None:
            on_list = on_commands if isinstance(on_commands, list) else [on_commands]
            if body in on_list:
                on_matches.append(key)
        off_commands = feature.get("off")
        if off_commands is not None:
            off_list = off_commands if isinstance(off_commands, list) else [off_commands]
            if body in off_list:
                off_matches.append(key)
    results = [(key, False) for key in off_matches]
    if len(on_matches) == 1:
        results.append((on_matches[0], True))
    return results


class PanasonicAWDriver(CameraDriver):
    """AW-series cameras (reference: AW-UE160) over CGI/HTTP.

    The notification feedback channel carries lens info (#LPC1, iris
    position only, via `start_lens_feedback()`/`stop_lens_feedback()`) and
    also update notifications for other events (`OAW`, `OWS`, etc.) --
    `_handle_notification()` matches the payload against known toggle
    feature/gain/pedestal commands in addition to `lPI`.

    `BUTTON_FEATURES`/`BUTTON_FEATURE_LABELS` and the gain/pedestal
    range/command (`_apply_model_catalog()`) are model-dependent, resolved
    from the model detected via `QID`. Iris position (`_IRIS_DATA_MIN/MAX`,
    #AXI/#GI) is only confirmed for AW-UE160; other models are unverified
    for this formula. Iris F-number (`_F_NUMBER_DATA_MIN/MAX`, QIF/OIF) is
    confirmed across models, gated per model by
    `supports_iris_f_number`/`SUPPORTS_IRIS_F_NUMBER`.

    Gain encoding (Data = 0x08 + db, 0x80 = AGC) is identical across models;
    only range/step (`gain_min_db`/`gain_max_db`/`gain_step_db`) vary and
    come from the model module. Pedestal has three different command
    families depending on model (`OSJ:0F` on AW-UE150/AW-UE160/AW-UE100,
    `OTP`/`QTP` on AW-HE50/60/120/130/HR140/HE40/UE70/HE42, `OSG:4A` on
    AK-UB300) -- command, center data value, scale, and hex width all come
    from the model module. Models without gain/pedestal data in the
    reference specs simply have no range (no invented fallback).
    """

    # Button 2/3 actions come from the per-camera-model BUTTON_FEATURES/
    # BUTTON_FEATURE_LABELS definition. These are instance attributes, not
    # class attributes: `connect()` resolves them from the model detected
    # via `QID` (see `_apply_model_catalog()`) -- an unknown model leaves
    # them empty rather than falling back to a guessed catalog.
    #
    # "toggle": on/off command (single string or list, see
    #   trigger_button_feature()); no query available, state is tracked
    #   locally only (see core/state.py).
    # "trigger": a one-shot command, no on/off state.
    # Multi-value camera parameters (knee, DRS) are modeled as one "toggle"
    # per target state (e.g. "knee_manual"/"knee_auto") rather than a
    # "cycle" type, since button 2/3 are physical two-state buttons with a
    # single, non-multicolor LED. The cycle concept still exists for button
    # 1 (Rec, encoder function selection) -- a separate mechanism unrelated
    # to BUTTON_FEATURES.
    BUTTON_FEATURES: dict[str, dict] = {}
    BUTTON_FEATURE_LABELS: dict[str, str] = {}

    def __init__(self, host: str, port: int = 80) -> None:
        self.host = host
        self.port = port
        self.model: str | None = None
        self._connected = False
        self._client: httpx.AsyncClient | None = None
        self._callbacks: list[Callable[[dict], None]] = []
        self._notify_server: asyncio.Server | None = None
        self._notify_port: int | None = None
        self._notify_heartbeat_task: asyncio.Task[None] | None = None
        self._last_notification_at: float = 0.0
        # Overwritten after connect() based on the detected model.
        self.BUTTON_FEATURES: dict[str, dict] = {}
        self.BUTTON_FEATURE_LABELS: dict[str, str] = {}
        # Gain/pedestal model data (see _apply_model_catalog()) -- `None`
        # means no model detected or not documented for this model.
        self.gain_min_db: int | None = None
        self.gain_max_db: int | None = None
        self.gain_step_db: int | None = None
        self.pedestal_command: str | None = None
        self.pedestal_query_command: str | None = None
        self.pedestal_min: int | None = None
        self.pedestal_max: int | None = None
        self.pedestal_center_data: int | None = None
        self.pedestal_scale: int | None = None
        self.pedestal_data_width: int | None = None
        # Super-gain coupling: only set for models with
        # GAIN_MAX_DB_SUPER_GAIN_OFF, otherwise both stay `None` and
        # `effective_gain_max_db` returns `gain_max_db` unchanged.
        self.gain_max_db_super_gain_off: int | None = None
        self.super_gain_query_command: str | None = None
        # Cached super-gain state, refreshed on every get_state() call.
        # `None` means "not queried yet", treated conservatively as off.
        self.gain_super_gain_on: bool | None = None
        # ND filter catalog (see _apply_model_catalog()) -- ordered
        # (data value, label) list; empty/`None` means this model has no
        # physical ND filter.
        self.nd_options: list[tuple[int, str]] | None = None
        # Iris F-number support (see _apply_model_catalog() and
        # query_f_number()) -- `False` means either an unknown model or one
        # without confirmed QIF support, no query is attempted.
        self.supports_iris_f_number: bool = False

    # --- Lifecycle -----------------------------------------------------

    async def connect(self) -> None:
        # A previous connect() that was never disconnect()'d -- e.g. a
        # camera_reconnect_loop() retry on an already-registered driver
        # that the liveness watchdog marked disconnected, which never goes
        # through register_camera()'s explicit old_driver.disconnect() --
        # would otherwise leak the old httpx.AsyncClient plus (if lens
        # feedback had been started) the old notification server/heartbeat
        # task, since they'd simply be overwritten below. disconnect() is a
        # no-op when there's nothing to clean up (fresh driver, `_client`
        # still `None`), so this doesn't change behavior for the normal
        # first-time-connect case.
        await self.disconnect()
        self._client = httpx.AsyncClient(
            base_url=f"http://{self.host}:{self.port}", timeout=_REQUEST_TIMEOUT
        )
        self.model = await self._query_model()
        self._connected = self.model is not None
        self._apply_model_catalog()

    def _apply_model_catalog(self) -> None:
        """Sets BUTTON_FEATURES/BUTTON_FEATURE_LABELS and gain/pedestal
        model data from the model detected via `QID`. Unknown or
        not-yet-connected model -> empty catalogs/`None` values."""
        module = resolve_model(self.model)
        self.BUTTON_FEATURES = dict(getattr(module, "BUTTON_FEATURES", {})) if module else {}
        self.BUTTON_FEATURE_LABELS = dict(getattr(module, "BUTTON_FEATURE_LABELS", {})) if module else {}
        self.gain_min_db = getattr(module, "GAIN_MIN_DB", None) if module else None
        self.gain_max_db = getattr(module, "GAIN_MAX_DB", None) if module else None
        self.gain_step_db = getattr(module, "GAIN_STEP_DB", None) if module else None
        self.pedestal_command = getattr(module, "PEDESTAL_COMMAND", None) if module else None
        self.pedestal_query_command = getattr(module, "PEDESTAL_QUERY_COMMAND", None) if module else None
        self.pedestal_min = getattr(module, "PEDESTAL_MIN", None) if module else None
        self.pedestal_max = getattr(module, "PEDESTAL_MAX", None) if module else None
        self.pedestal_center_data = getattr(module, "PEDESTAL_CENTER_DATA", None) if module else None
        self.pedestal_scale = getattr(module, "PEDESTAL_SCALE", None) if module else None
        self.pedestal_data_width = getattr(module, "PEDESTAL_DATA_WIDTH", None) if module else None
        self.gain_max_db_super_gain_off = (
            getattr(module, "GAIN_MAX_DB_SUPER_GAIN_OFF", None) if module else None
        )
        self.super_gain_query_command = getattr(module, "SUPER_GAIN_QUERY_COMMAND", None) if module else None
        nd_options = getattr(module, "ND_FILTER_OPTIONS", None) if module else None
        self.nd_options = list(nd_options) if nd_options else None
        self.supports_iris_f_number = bool(getattr(module, "SUPPORTS_IRIS_F_NUMBER", False)) if module else False

    async def disconnect(self) -> None:
        await self.stop_lens_feedback()
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._connected = False

    # --- Lens-info feedback (iris changes from other sources) --
    # Not part of the CameraDriver ABC -- the application layer checks via
    # hasattr() whether a driver offers this.

    async def start_lens_feedback(self) -> None:
        """Registers the update-notification channel and enables lens info
        (#LPC1). The primary source for iris feedback on externally
        triggered changes (e.g. the camera's own web UI), since the
        iris-set command itself carries no update-notification flag."""
        if self._client is None:
            raise CameraCommandError("not connected")
        server = await asyncio.start_server(self._handle_notification, "0.0.0.0", 0)
        self._notify_server = server
        self._notify_port = server.sockets[0].getsockname()[1]
        await self._notify_request("start")
        await self._request("aw_ptz", "#LPC1")
        self._last_notification_at = time.monotonic()
        self._notify_heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def stop_lens_feedback(self) -> None:
        if self._notify_heartbeat_task is not None:
            self._notify_heartbeat_task.cancel()
            try:
                await self._notify_heartbeat_task
            except asyncio.CancelledError:
                pass
            self._notify_heartbeat_task = None
        if self._notify_server is not None:
            try:
                await self._request("aw_ptz", "#LPC0")
            except CameraCommandError:
                pass
            try:
                await self._notify_request("stop")
            except httpx.HTTPError:
                pass
            self._notify_server.close()
            await self._notify_server.wait_closed()
            self._notify_server = None
            self._notify_port = None

    async def _notify_request(self, action: str) -> None:
        assert self._client is not None
        url = f"/cgi-bin/event?connect={action}&my_port={self._notify_port}&uid=0"
        await self._client.get(url)

    async def _handle_notification(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Each notification arrives as its own short-lived TCP connection
        with exactly one frame.

        Over the same update-notification channel already registered for
        lens info (`lPI`), the camera reports every change to a control
        command, regardless of whether it was triggered by this app or
        another terminal (e.g. the camera's own web UI). The payload is the
        exact same command string as when sending (e.g. 'OGU:08'), so
        matching against the known commands from BUTTON_FEATURES/gain/
        pedestal is enough -- no new parsing needed. Some commands (OSD menu
        navigation, pan/tilt/zoom/focus/iris, one-touch focus, contrast,
        iris volume) trigger no notification at all -- this includes
        `auto_focus` (`OAF`) and `auto_iris` (`ORS`): those two catalog
        entries only get an updated value on the next explicit query
        (assignment, app restart), never push-based on an external change."""
        try:
            frame = await reader.read(65536)
        finally:
            writer.close()
        self._last_notification_at = time.monotonic()
        body = _parse_notification_payload(frame)
        if body is None:
            return
        iris = _parse_lens_info_iris(body)
        if iris is not None:
            for callback in self._callbacks:
                callback({"type": "iris_changed", "value": iris})
            return
        toggle_matches = _match_toggle_feature(body, self.BUTTON_FEATURES)
        if toggle_matches:
            for key, enabled in toggle_matches:
                for callback in self._callbacks:
                    callback({"type": "feature_changed", "key": key, "enabled": enabled})
            return
        if body.startswith("OGU:"):
            value = _extract_value(body)
            if value is not None:
                try:
                    gain_db, gain_auto = _decode_gain_data(int(value, 16))
                except ValueError:
                    gain_db, gain_auto = None, None
                if gain_auto is not None:
                    for callback in self._callbacks:
                        callback({"type": "gain_changed", "value": gain_db, "auto": gain_auto})
            return
        if self.pedestal_command is not None and body.startswith(f"{self.pedestal_command}:"):
            value = _extract_value(body)
            if value is not None:
                try:
                    pedestal = self._decode_pedestal_data(int(value, 16))
                except ValueError:
                    pedestal = None
                if pedestal is not None:
                    for callback in self._callbacks:
                        callback({"type": "pedestal_changed", "value": pedestal})
            return
        if body.startswith("OFT:"):
            # ND filter. Unlike OGU/pedestal, the data field here is a plain
            # decimal value (see set_nd()/_query_nd()), not a hex string.
            value = _extract_value(body)
            if value is not None:
                try:
                    nd_index = int(value)
                except ValueError:
                    nd_index = None
                if nd_index is not None:
                    for callback in self._callbacks:
                        callback({"type": "nd_changed", "value": nd_index})

    async def _heartbeat_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(_NOTIFY_REREGISTER_INTERVAL)
                try:
                    if time.monotonic() - self._last_notification_at > _NOTIFY_HEARTBEAT_TIMEOUT:
                        await self._reregister_lens_feedback()
                    else:
                        # Re-send the registration on the existing socket, so
                        # a slot stolen by another client (e.g. the camera's
                        # own web UI) gets reclaimed even while QSV
                        # heartbeats keep arriving and the silence timeout
                        # above never fires.
                        await self._notify_request("start")
                except httpx.HTTPError as exc:
                    LOGGER.warning("Notification-Registrierung fehlgeschlagen fuer %s: %s", self.host, exc)
        except asyncio.CancelledError:
            raise

    async def _reregister_lens_feedback(self) -> None:
        if self._notify_server is not None:
            self._notify_server.close()
            await self._notify_server.wait_closed()
        server = await asyncio.start_server(self._handle_notification, "0.0.0.0", 0)
        self._notify_server = server
        self._notify_port = server.sockets[0].getsockname()[1]
        await self._notify_request("start")
        self._last_notification_at = time.monotonic()

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def effective_gain_max_db(self) -> int | None:
        """Actually usable gain upper bound -- on models with super-gain
        coupling, lower than `gain_max_db` until super gain is positively
        confirmed on (values above that are rejected by the camera).
        Unknown state is treated conservatively as off. Models without this
        coupling return `gain_max_db` unchanged."""
        if self.gain_max_db_super_gain_off is not None and self.gain_super_gain_on is not True:
            return self.gain_max_db_super_gain_off
        return self.gain_max_db

    async def _query_super_gain(self) -> bool | None:
        if self.super_gain_query_command is None:
            return None
        try:
            body = await self._request("aw_cam", self.super_gain_query_command)
        except CameraCommandError:
            return None
        value = _extract_value(body)
        if value is None:
            return None
        try:
            return int(value, 16) == 1
        except ValueError:
            return None

    # --- Steuerung -------------------------------------------------------

    async def set_iris(self, value: float) -> None:
        data = _iris_to_data(value)
        await self._request("aw_ptz", f"#AXI{data:03X}")

    async def set_auto_iris(self, on: bool) -> None:
        await self._request("aw_cam", f"ORS:{1 if on else 0}")

    async def set_gain_db(self, db: int) -> None:
        data = _GAIN_ZERO_DB_DATA + db
        await self._request("aw_cam", f"OGU:{data:02X}")

    async def set_gain_auto(self) -> None:
        """Gain "Auto"/AGC (Data=0x80) -- a regular third gain state, not
        an error."""
        await self._request("aw_cam", f"OGU:{_GAIN_AGC_DATA:02X}")

    async def step_gain(self, delta_db: int) -> tuple[int | None, bool]:
        """Returns (new dB value or `None` if Auto, is_auto). Auto
        (Data=0x80) is a regular third gain state at the lower end: turning
        down below `gain_min_db` switches to Auto, turning up from Auto
        leaves it again.

        Exiting is proportional to the turn delta -- Auto is treated as a
        virtual position one step below `gain_min_db`, so a fast/strong
        turn-up lands proportionally further up like any other value, still
        clamped to `effective_gain_max_db`. Turning down further while in
        Auto is a no-op (no lower state than Auto)."""
        current_db, current_auto = await self._query_gain_state()
        if current_db is None and not current_auto:
            raise CameraCommandError("gain step ignored: gain unreadable")
        if self.gain_min_db is None or self.gain_max_db is None:
            raise CameraCommandError("gain step ignored: no gain range known for this model")
        if current_auto:
            if delta_db <= 0:
                return None, True
            new_db = min(self.effective_gain_max_db, self.gain_min_db + (delta_db - 1))
            await self.set_gain_db(new_db)
            return new_db, False
        new_db = current_db + delta_db
        if new_db < self.gain_min_db:
            await self.set_gain_auto()
            return None, True
        new_db = min(self.effective_gain_max_db, new_db)
        await self.set_gain_db(new_db)
        return new_db, False

    async def set_pedestal(self, value: int) -> None:
        if (
            self.pedestal_command is None
            or self.pedestal_center_data is None
            or self.pedestal_scale is None
            or self.pedestal_data_width is None
        ):
            raise CameraCommandError("pedestal not supported for this model")
        data = self.pedestal_center_data + value * self.pedestal_scale
        await self._request("aw_cam", f"{self.pedestal_command}:{data:0{self.pedestal_data_width}X}")

    async def step_pedestal(self, delta: int) -> int:
        current = await self._query_pedestal()
        if current is None:
            raise CameraCommandError("pedestal step ignored: pedestal unreadable")
        if self.pedestal_min is None or self.pedestal_max is None:
            raise CameraCommandError("pedestal step ignored: no pedestal range known for this model")
        new_value = max(self.pedestal_min, min(self.pedestal_max, current + delta))
        await self.set_pedestal(new_value)
        return new_value

    async def set_rb_gain(self, r: int | None, b: int | None) -> None:
        if r is not None:
            data = _RB_GAIN_CENTER_DATA + r
            await self._request("aw_cam", f"OSL:36:{data:03X}")
        if b is not None:
            data = _RB_GAIN_CENTER_DATA + b
            await self._request("aw_cam", f"OSL:38:{data:03X}")

    async def set_nd(self, index: int) -> None:
        """`index` is the raw data value (not the list position) -- valid
        values are model-dependent per `self.nd_options`; some models have
        a sparse value list (e.g. only 0/3/4)."""
        if not self.nd_options:
            raise CameraCommandError("ND filter not supported for this model")
        valid_indices = {opt_index for opt_index, _ in self.nd_options}
        if index not in valid_indices:
            raise ValueError(f"ND index out of range: {index}")
        await self._request("aw_cam", f"OFT:{index}")

    async def cycle_nd(self) -> int:
        """Wraps around through `self.nd_options` -- unlike the encoder
        function (which clamps instead of wrapping), since this serves a
        single, directionless button press."""
        if not self.nd_options:
            raise CameraCommandError("ND filter not supported for this model")
        positions = [opt_index for opt_index, _ in self.nd_options]
        current = await self._query_nd()
        current_position = positions.index(current) if current in positions else -1
        new_index = positions[(current_position + 1) % len(positions)]
        await self.set_nd(new_index)
        return new_index

    async def trigger_awb(self) -> None:
        await self._request("aw_cam", "OWS")

    async def set_bars(self, on: bool) -> None:
        await self._request("aw_cam", f"DCB:{1 if on else 0}")

    async def recall_preset(self, number: int) -> None:
        if not 0 <= number <= 99:
            raise ValueError(f"preset number out of range: {number}")
        await self._request("aw_ptz", f"#R{number:02d}")

    # --- Camera feature buttons (BUTTON_FEATURES catalog) -----------------
    # Not part of the CameraDriver ABC -- the application layer only
    # accesses this via getattr(driver, "BUTTON_FEATURES", {}); a driver
    # without a catalog simply offers no options.

    async def trigger_button_feature(self, key: str, *, enabled: bool | None = None) -> None:
        """Toggle (needs `enabled`) or trigger (ignores `enabled`).
        `auto_iris` delegates to the existing typed method to avoid
        duplicating command logic.

        `feature["on"]`/`feature["off"]`/`feature["cmd"]` are usually a
        single command string, but can also be a list: multi-value camera
        parameters like knee need more than one command for a single target
        state (e.g. AW-UE160's "Knee: Auto" sends `OSL:45:1` then
        `OSA:2D:2`, in that order)."""
        if key == "auto_iris":
            if enabled is None:
                raise ValueError("'auto_iris' ist ein Toggle, 'enabled' erforderlich")
            await self.set_auto_iris(enabled)
            return
        feature = self.BUTTON_FEATURES.get(key)
        if feature is None:
            raise ValueError(f"unbekanntes Button-Feature: {key!r}")
        if feature["kind"] == "toggle":
            if enabled is None:
                raise ValueError(f"{key!r} ist ein Toggle, 'enabled' erforderlich")
            commands = feature["on"] if enabled else feature["off"]
        elif feature["kind"] == "trigger":
            commands = feature["cmd"]
        else:
            raise ValueError(f"{key!r}: unbekannte Feature-Art {feature['kind']!r}")
        if isinstance(commands, str):
            commands = [commands]
        for cmd in commands:
            await self._request("aw_cam", cmd)

    async def query_button_feature(self, key: str) -> bool | None:
        """Queries the current state of a toggle button feature.

        `auto_iris` is a special case, like in `trigger_button_feature()` --
        uses the existing iris query (`#GI` mode bit) rather than its own
        query command. For all other toggle features this reads
        `feature["query"]`/`feature["query_on_value"]` (only set where a
        query command is confirmed) -- missing either returns `None`."""
        if key == "auto_iris":
            _, auto_iris = await self.query_iris()
            return auto_iris
        feature = self.BUTTON_FEATURES.get(key)
        if feature is None or feature.get("kind") != "toggle":
            return None
        query_cmd = feature.get("query")
        query_on_value = feature.get("query_on_value")
        if query_cmd is None or query_on_value is None:
            return None
        try:
            body = await self._request("aw_cam", query_cmd)
        except CameraCommandError:
            return None
        value = _extract_value(body)
        if value is None:
            return None
        try:
            return int(value, 16) == int(query_on_value, 16)
        except ValueError:
            return None

    # --- Status ----------------------------------------------------------

    async def get_state(self) -> CameraState:
        iris, auto_iris = await self.query_iris()
        gain_db, gain_auto = await self._query_gain_state()
        # Refreshes the cached super-gain state (see effective_gain_max_db)
        # -- get_state() runs on connect() and on every switch of the
        # encoder function to "gain", so this stays reasonably fresh without
        # querying on every single encoder tick.
        if self.super_gain_query_command is not None:
            self.gain_super_gain_on = await self._query_super_gain()
        return CameraState(
            iris=iris,
            iris_f_number=await self.query_f_number(),
            auto_iris=auto_iris,
            gain_db=gain_db,
            gain_auto=gain_auto,
            pedestal=await self._query_pedestal(),
            nd_index=await self._query_nd(),
            error=await self._query_error(),
        )

    async def ping(self) -> None:
        """Re-sends the same lightweight `QID` query used to detect the
        model at connect time -- unlike `_query_model()`, doesn't swallow
        `CameraCommandError`, so the liveness watchdog can tell success from
        failure. `_request()` already flips `connected` to `False` on
        failure, same as any other command."""
        await self._request("aw_cam", "QID")

    def subscribe(self, callback: Callable[[dict], None]) -> None:
        self._callbacks.append(callback)

    # --- internal query helpers ---------------------------------------

    async def _query_model(self) -> str | None:
        try:
            body = await self._request("aw_cam", "QID")
        except CameraCommandError:
            return None
        return _extract_value(body)

    async def query_iris(self) -> tuple[float | None, bool | None]:
        # apply_iris() re-queries this while auto-iris is active, to get the
        # real (unchanged by the iris-set command) position + mode instead
        # of trusting the fader's target value.
        try:
            body = await self._request("aw_ptz", "#GI")
        except CameraCommandError:
            return None, None
        # Response format gi[Pos][Mode]: "gi" + 3 hex digits pos + 1 hex digit mode
        if len(body) < 6 or not body.lower().startswith("gi"):
            return None, None
        try:
            pos = int(body[2:5], 16)
            mode = int(body[5:6], 16)
        except ValueError:
            return None, None
        return _data_to_iris(pos), (mode == 1)

    async def query_f_number(self) -> str | None:
        # Falls back to the raw hex value if `data` is outside the confirmed
        # range or not parsable as hex. core/application.py::apply_iris()
        # calls this on every fader tick so the F-number stays live during a
        # drag; a single QIF query is cheap enough for that.
        #
        # Skipped entirely for models without confirmed QIF support
        # (`supports_iris_f_number`), avoiding pointless requests on cameras
        # that would just answer with an error.
        if not self.supports_iris_f_number:
            return None
        try:
            body = await self._request("aw_cam", "QIF")
        except CameraCommandError:
            return None
        value = _extract_value(body)
        if value is None:
            return None
        try:
            data = int(value, 16)
        except ValueError:
            return value
        return _decode_f_number(data) or value

    async def _query_gain_state(self) -> tuple[int | None, bool | None]:
        # Returns (dB value or None if Auto, is_auto) -- None here means
        # "unreadable", not Auto.
        try:
            body = await self._request("aw_cam", "QGU")
        except CameraCommandError:
            return None, None
        value = _extract_value(body)
        if value is None:
            return None, None
        return _decode_gain_data(int(value, 16))

    def _decode_pedestal_data(self, data: int) -> int | None:
        """Pedestal encoding of the connected model (`pedestal_center_data`/
        `pedestal_scale`), shared between `_query_pedestal()` and the
        update-notification handling -- both decode the same `[Data]` from
        a query response or notification payload."""
        if self.pedestal_center_data is None or self.pedestal_scale is None:
            return None
        return (data - self.pedestal_center_data) // self.pedestal_scale

    async def _query_pedestal(self) -> int | None:
        # Query command comes from the resolved model module -- unknown/
        # undocumented model -> no query.
        if (
            self.pedestal_query_command is None
            or self.pedestal_center_data is None
            or self.pedestal_scale is None
        ):
            return None
        try:
            body = await self._request("aw_cam", self.pedestal_query_command)
        except CameraCommandError:
            return None
        value = _extract_value(body)
        if value is None:
            return None
        try:
            data = int(value, 16)
        except ValueError:
            return None
        return self._decode_pedestal_data(data)

    async def _query_nd(self) -> int | None:
        try:
            body = await self._request("aw_cam", "QFT")
        except CameraCommandError:
            return None
        value = _extract_value(body)
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    async def _query_error(self) -> str | None:
        try:
            body = await self._request("aw_cam", "QER")
        except CameraCommandError:
            return None
        if body.startswith(_ERROR_STATE_PREFIXES):
            return body
        return None

    # --- HTTP transport ----------------------------------------------------

    async def _request(self, endpoint: str, cmd: str) -> str:
        if self._client is None:
            raise CameraCommandError("not connected")

        encoded_cmd = cmd.replace("#", "%23")
        url = f"/cgi-bin/{endpoint}?cmd={encoded_cmd}&res=1"

        try:
            response = await self._client.get(url)
        except httpx.TimeoutException:
            try:
                response = await self._client.get(url)  # one retry
            except httpx.HTTPError as exc:
                self._connected = False
                raise CameraCommandError(f"timeout: {cmd}") from exc
        except httpx.HTTPError as exc:
            self._connected = False
            raise CameraCommandError(f"connection error: {cmd}: {exc}") from exc

        body = response.text.strip()
        error_prefixes = (
            _ERROR_PREFIXES_PTZ if endpoint == "aw_ptz" else _ERROR_PREFIXES_CAM
        )
        if body.startswith(error_prefixes):
            raise CameraCommandError(f"camera error for '{cmd}': {body}")
        return body
