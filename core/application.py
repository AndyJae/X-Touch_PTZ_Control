"""core/application.py -- Application layer.

Wires config/drivers/mapping engine/rate limiter/event bus into a running
process state (`AppState`) and exposes the use cases an interface (web UI,
X-Touch/MIDI) calls: `connect_camera`, `apply_iris`, `channel_snapshot`,
`register_camera`. Only touches FastAPI at the narrow point where WebSocket
clients are notified (`AppState.broadcast`) -- routing/templates live in
`web/app.py`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import httpx
from fastapi import WebSocket

from core.bus import EventBus
from core.companion import build_client, press_button
from core.config import (
    AppConfig,
    BankChannelConfig,
    BankConfig,
    CameraConfig,
    CompanionConfig,
    CompanionTarget,
    MidiConfig,
    save_config,
)
from core.mapping import MappingEngine, build_mapping_from_config
from core.ratelimit import RateLimiter
from core.state import StateStore
from drivers.base import CameraCommandError, CameraDriver
from drivers.panasonic_aw import PanasonicAWDriver

LOGGER = logging.getLogger("ptz_control.application")

# Iris hysteresis: 1 digit of the device's target range (555h-FFFh -> 2730 steps).
_IRIS_HYSTERESIS = 1.0 / (0xFFF - 0x555)


def build_driver(camera: CameraConfig) -> CameraDriver:
    if camera.driver != "panasonic_aw":
        raise ValueError(f"unsupported driver: {camera.driver!r}")
    return PanasonicAWDriver(host=camera.host, port=camera.port)


@dataclass
class AppState:
    """Per-process runtime state, attached to `app.state.ptz`."""

    config: AppConfig
    event_bus: EventBus
    state_store: StateStore
    mapping: MappingEngine
    cameras: dict[str, CameraConfig]
    drivers: dict[str, CameraDriver]
    rate_limiters: dict[str, RateLimiter]
    config_path: str = "config.yaml"
    ws_clients: set[WebSocket] = field(default_factory=set)
    companion_client: httpx.AsyncClient = field(default_factory=build_client)
    # Encoder function selection per channel (button 1/Rec) -- index into
    # `_ENCODER_FUNCTIONS`, runtime-only like `feature_states`.
    encoder_function_index: dict[int, int] = field(default_factory=dict)
    # Timestamps of recent encoder ticks per channel, for the acceleration
    # rule in `_encoder_multiplier`.
    encoder_tick_history: dict[int, list[float]] = field(default_factory=dict)
    # Delta a turn tick wants to apply but the rate limiter is currently
    # holding back -- replayed on the next allowed tick.
    encoder_pending_delta: dict[int, int] = field(default_factory=dict)
    # Visual "saved" flag per channel (encoder push): shown in the web UI
    # until the next turn tick clears it.
    encoder_saved: dict[int, bool] = field(default_factory=dict)
    # Encoder turns send gain/pedestal live per tick -- separate rate
    # limiter instance per camera so not every MIDI tick triggers its own
    # HTTP request.
    encoder_rate_limiters: dict[str, RateLimiter] = field(default_factory=dict)
    # Whether the saved Companion config was actually confirmed reachable
    # (via is_reachable), independent of whether a host is configured at all.
    companion_connected: bool = False
    # Startup dialog ("Load previous config"/"Start new config"): True until
    # one of the two web UI actions answers it, then False for the rest of
    # the process. Runtime-only, not persisted.
    startup_choice_pending: bool = True

    async def broadcast(self, payload: dict) -> None:
        stale: list[WebSocket] = []
        for ws in self.ws_clients:
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.ws_clients.discard(ws)


def build_app_state(config: AppConfig, config_path: str = "config.yaml") -> AppState:
    cameras = {cam.id: cam for cam in config.cameras}
    drivers: dict[str, CameraDriver] = {cid: build_driver(cam) for cid, cam in cameras.items()}
    rate_limiters = {
        cid: RateLimiter(config.global_.rate_limit_hz, hysteresis=_IRIS_HYSTERESIS) for cid in cameras
    }
    encoder_rate_limiters = {cid: RateLimiter(config.global_.rate_limit_hz) for cid in cameras}
    state = AppState(
        config=config,
        event_bus=EventBus(),
        state_store=StateStore(),
        mapping=build_mapping_from_config(config),
        cameras=cameras,
        drivers=drivers,
        rate_limiters=rate_limiters,
        encoder_rate_limiters=encoder_rate_limiters,
        config_path=config_path,
    )
    _subscribe_snapshot_broadcast(state)
    return state


def _subscribe_snapshot_broadcast(state: AppState) -> None:
    """Broadcasts a full state snapshot to all WebSocket clients whenever a
    camera domain event fires (`iris_changed`, `connection_changed`,
    `error`, `feature_changed`, `config_changed`, `gain_changed`,
    `pedestal_changed`, `nd_changed`)."""

    async def _on_camera_event(_payload: dict) -> None:
        await state.broadcast({"type": "snapshot", "channels": channel_snapshot(state)})

    for topic in (
        "iris_changed",
        "connection_changed",
        "error",
        "feature_changed",
        "config_changed",
        "gain_changed",
        "pedestal_changed",
        "nd_changed",
    ):
        state.event_bus.subscribe(topic, _on_camera_event)


def _channel_config(state: AppState, channel_index: int) -> BankChannelConfig | None:
    banks = state.config.banks
    if not banks:
        return None
    channels = banks[0].channels
    if not 1 <= channel_index <= len(channels):
        return None
    return channels[channel_index - 1]


async def _refresh_f_number_from_notification(state: AppState, camera_id: str, driver: CameraDriver) -> None:
    """Re-queries just the F-number (`driver.query_f_number()`, not the full
    `get_state()`) and re-publishes `iris_changed` so the web UI snapshot
    and scribble strip pick up the refreshed value."""
    cam_state = state.state_store.get_camera(camera_id)
    cam_state.iris_f_number = await driver.query_f_number()
    await state.event_bus.publish("iris_changed", {"camera_id": camera_id, "value": cam_state.iris})


def _wire_camera_events(state: AppState, camera_id: str, driver: CameraDriver) -> None:
    """Bridges driver events (`subscribe()`, sync) onto the async event bus,
    so the web UI and MIDI motor fader also react to changes triggered
    outside this app (e.g. the camera's own web UI)."""

    def on_event(event: dict) -> None:
        event_type = event.get("type")
        if event_type == "iris_changed":
            cam_state = state.state_store.get_camera(camera_id)
            position_changed = cam_state.iris != event["value"]
            cam_state.iris = event["value"]
            asyncio.create_task(
                state.event_bus.publish("iris_changed", {"camera_id": camera_id, "value": event["value"]})
            )
            if position_changed:
                # The lens-info notification frame only carries the raw iris
                # position, not the F-number -- re-query it, but only on an
                # actual position change, not on every notification heartbeat.
                asyncio.create_task(_refresh_f_number_from_notification(state, camera_id, driver))
        elif event_type == "feature_changed":
            cam_state = state.state_store.get_camera(camera_id)
            cam_state.feature_states[event["key"]] = event["enabled"]
            if event["enabled"]:
                # Externally triggered change (e.g. the camera's own web UI)
                # -- keep exclusive_with siblings (see apply_button_action())
                # in sync the same way a locally triggered change does.
                feature = getattr(driver, "BUTTON_FEATURES", {}).get(event["key"], {})
                for sibling in feature.get("exclusive_with", []):
                    cam_state.feature_states[sibling] = False
            asyncio.create_task(
                state.event_bus.publish("feature_changed", {"camera_id": camera_id, "key": event["key"]})
            )
        elif event_type == "gain_changed":
            cam_state = state.state_store.get_camera(camera_id)
            cam_state.gain_db = event["value"]
            cam_state.gain_auto = event.get("auto", False)
            asyncio.create_task(
                state.event_bus.publish(
                    "gain_changed", {"camera_id": camera_id, "value": event["value"], "auto": cam_state.gain_auto}
                )
            )
        elif event_type == "pedestal_changed":
            state.state_store.get_camera(camera_id).pedestal = event["value"]
            asyncio.create_task(
                state.event_bus.publish("pedestal_changed", {"camera_id": camera_id, "value": event["value"]})
            )
        elif event_type == "nd_changed":
            state.state_store.get_camera(camera_id).nd_index = event["value"]
            asyncio.create_task(
                state.event_bus.publish("nd_changed", {"camera_id": camera_id, "value": event["value"]})
            )

    driver.subscribe(on_event)


async def connect_camera(state: AppState, camera_id: str) -> None:
    """`connect()` -> `QID` -> `get_state()`, then starts lens-info feedback
    for drivers that offer it (accessed via `hasattr()`, not part of the
    CameraDriver ABC -- a driver without support simply won't deliver
    external iris updates)."""
    driver = state.drivers[camera_id]
    cam_state = state.state_store.get_camera(camera_id)
    _wire_camera_events(state, camera_id, driver)
    try:
        await driver.connect()
        if not driver.connected:
            cam_state.error = "Verbindung fehlgeschlagen (QID nicht erreichbar/keine Antwort)"
            return
        try:
            full_state = await driver.get_state()
        except CameraCommandError as exc:
            cam_state.error = str(exc)
            return
        full_state.error = None
        state.state_store.set_camera(camera_id, full_state)
        LOGGER.info("Kamera %s verbunden (Modell %s)", camera_id, driver.model)
        start_lens_feedback = getattr(driver, "start_lens_feedback", None)
        if start_lens_feedback is not None:
            try:
                await start_lens_feedback()
            except CameraCommandError as exc:
                LOGGER.warning("Kamera %s: Lens-Info-Feedback fehlgeschlagen: %s", camera_id, exc)
    finally:
        await state.event_bus.publish("connection_changed", {"camera_id": camera_id})


async def disconnect_camera(state: AppState, camera_id: str) -> None:
    """Disconnects a camera and removes its registration entirely from
    `config.yaml` -- a subsequent "Connect Camera" needs name/IP/port again.

    Resets `iris` to 0.0 and publishes `connection_changed` first, while the
    channel mapping still exists, so the physical motor fader can be driven
    to 0 before the channel mapping, bank entry, and camera config are
    removed and `config_changed` is published."""
    driver = state.drivers.get(camera_id)
    if driver is None:
        return
    await driver.disconnect()
    LOGGER.info("Kamera %s getrennt und aus config.yaml entfernt", camera_id)
    cam_state = state.state_store.get_camera(camera_id)
    cam_state.error = None
    cam_state.iris = 0.0
    await state.event_bus.publish("connection_changed", {"camera_id": camera_id})

    channel_index = next(
        (
            index
            for index, mapping in state.mapping.channels_for_type("fader").items()
            if mapping.camera_id == camera_id
        ),
        None,
    )
    state.config.cameras = [c for c in state.config.cameras if c.id != camera_id]
    if channel_index is not None:
        if state.config.banks and 1 <= channel_index <= len(state.config.banks[0].channels):
            state.config.banks[0].channels[channel_index - 1] = None
        state.mapping.unset_channel("fader", channel_index)
    save_config(state.config_path, state.config)

    state.cameras.pop(camera_id, None)
    state.drivers.pop(camera_id, None)
    state.rate_limiters.pop(camera_id, None)
    state.encoder_rate_limiters.pop(camera_id, None)
    await state.event_bus.publish("config_changed", {"channel_index": channel_index})


async def reset_to_new_config(state: AppState) -> None:
    """"Start new config" (startup dialog): disconnects every currently
    connected camera and resets Companion/MIDI/bank/channel config to schema
    defaults, so `config.yaml` ends up matching a freshly created file."""
    for camera_id in list(state.drivers):
        await disconnect_camera(state, camera_id)
    state.config.banks = []
    state.config.midi = MidiConfig()
    state.config.companion = CompanionConfig()
    state.companion_connected = False
    state.mapping = MappingEngine()
    state.encoder_function_index.clear()
    state.encoder_tick_history.clear()
    state.encoder_pending_delta.clear()
    state.encoder_saved.clear()
    save_config(state.config_path, state.config)
    await state.event_bus.publish("config_changed", {})


async def register_camera(
    state: AppState, channel_index: int, *, name: str, host: str, port: int
) -> None:
    """Registers or updates a camera for a channel via the Setup page's
    "Connect Camera" button. The camera ID is deterministic (`cam{channel}`);
    calling this again for the same channel updates that camera instead of
    creating a second one.

    Rejects a host IP already assigned to a different channel -- two
    channels pointing at the same physical camera would silently share
    state (lens-info push, gain, pedestal). The same host on the same
    channel (reconnect/update) remains allowed."""
    if not 1 <= channel_index <= 8:
        raise ValueError(f"Kanal außerhalb 1-8: {channel_index}")
    if not host:
        raise ValueError("Host darf nicht leer sein")
    camera_id = f"cam{channel_index}"
    duplicate = next((c for c in state.config.cameras if c.host == host and c.id != camera_id), None)
    if duplicate is not None:
        raise ValueError("Camera is already connected, please select another camera")

    camera_cfg = CameraConfig(
        id=camera_id,
        name=name or f"CAM {channel_index}",
        driver="panasonic_aw",
        host=host,
        port=port,
    )
    state.config.cameras = [c for c in state.config.cameras if c.id != camera_id] + [camera_cfg]

    if not state.config.banks:
        state.config.banks = [BankConfig(name="Bank A", channels=[])]
    channels = state.config.banks[0].channels
    while len(channels) < 8:
        channels.append(None)
    channels[channel_index - 1] = BankChannelConfig(camera=camera_id)

    save_config(state.config_path, state.config)

    old_driver = state.drivers.get(camera_id)
    if old_driver is not None:
        await old_driver.disconnect()

    state.cameras[camera_id] = camera_cfg
    state.drivers[camera_id] = build_driver(camera_cfg)
    state.rate_limiters[camera_id] = RateLimiter(
        state.config.global_.rate_limit_hz, hysteresis=_IRIS_HYSTERESIS
    )
    state.encoder_rate_limiters[camera_id] = RateLimiter(state.config.global_.rate_limit_hz)
    state.mapping.set_channel("fader", channel_index, camera_id)

    await connect_camera(state, camera_id)


async def rename_camera(state: AppState, channel_index: int, name: str) -> None:
    """Updates only the display name of an already-registered camera,
    independent of the connect/disconnect toggle so renaming never drops an
    existing connection. No effect if the channel has no camera yet."""
    entry = state.mapping.get_channel("fader", channel_index)
    if entry is None:
        return
    camera_cfg = state.cameras.get(entry.camera_id)
    if camera_cfg is None:
        return
    camera_cfg.name = name.strip() or f"CAM {channel_index}"
    save_config(state.config_path, state.config)
    await state.event_bus.publish("config_changed", {"channel_index": channel_index})


async def configure_companion(state: AppState, host: str, port: int, connected: bool = False) -> None:
    """Saves the single global Bitfocus Companion instance shared across all
    channels. `connected` comes from the caller, which has already checked
    reachability via `is_reachable` -- not re-checked here to avoid
    duplicating the request."""
    state.config.companion.host = host.strip()
    state.config.companion.port = port
    state.companion_connected = connected
    save_config(state.config_path, state.config)
    await state.event_bus.publish("config_changed", {})


async def assign_channel_companion_target(
    state: AppState, channel_index: int, page: int | None, row: int | None, column: int | None
) -> None:
    """Persists a channel's SELECT button target (Companion page/row/column).
    `page/row/column=None` clears the assignment."""
    channel_cfg = _channel_config(state, channel_index)
    if channel_cfg is None:
        raise ValueError(f"Kanal {channel_index} hat keine Kamera zugewiesen")
    if page is None or row is None or column is None:
        channel_cfg.companion = None
    else:
        channel_cfg.companion = CompanionTarget(page=page, row=row, column=column)
    save_config(state.config_path, state.config)
    await state.event_bus.publish("config_changed", {"channel_index": channel_index})


async def trigger_companion_select(state: AppState, channel_index: int) -> None:
    """Fires a channel's SELECT button target in Companion. No effect
    without an assigned target. Re-raises `CompanionError` on a connection
    error/non-2xx response so the caller can report it -- SELECT is a
    one-shot action with no persistent state in the snapshot."""
    channel_cfg = _channel_config(state, channel_index)
    target = channel_cfg.companion if channel_cfg else None
    if target is None:
        return
    await press_button(
        state.companion_client,
        state.config.companion.host,
        state.config.companion.port,
        target.page,
        target.row,
        target.column,
    )
    LOGGER.info(
        "Kanal %s: Companion SELECT ausgeloest (Page %s/Row %s/Col %s)",
        channel_index,
        target.page,
        target.row,
        target.column,
    )


async def apply_iris(state: AppState, channel_index: int, value: float, *, final: bool) -> None:
    """Fader -> camera data flow: mapping -> rate limiter -> driver.

    Re-queries the F-number display (`driver.query_f_number()`) after every
    tick the rate limiter actually lets through, not just on `final=True` --
    unlike iris %, there's no formula for F-number from the fader position,
    only the camera's own query.

    The camera silently ignores iris-set commands while auto-iris is active
    (no error, but no effect on the real position). If `cam_state.auto_iris`
    is `True`, the fader's target value is therefore not applied blindly;
    instead the real position and auto-iris mode are re-queried and
    published, so the web slider and motor fader snap back to the real
    position on every tick while auto-iris stays active. When auto-iris is
    off, the cheaper direct-apply behavior is unchanged."""
    entry = state.mapping.get_channel("fader", channel_index)
    if entry is None:
        return
    camera_id = entry.camera_id
    driver = state.drivers.get(camera_id)
    limiter = state.rate_limiters.get(camera_id)
    if driver is None or limiter is None or not driver.connected:
        return
    value = max(0.0, min(1.0, value))
    if not limiter.should_send(value, final=final):
        return
    cam_state = state.state_store.get_camera(camera_id)
    try:
        await driver.set_iris(value)
    except CameraCommandError as exc:
        cam_state.error = str(exc)
        await state.event_bus.publish("error", {"camera_id": camera_id, "message": str(exc)})
        return
    cam_state.error = None
    if cam_state.auto_iris:
        real_iris, real_auto_iris = await driver.query_iris()
        if real_iris is not None:
            cam_state.iris = real_iris
        if real_auto_iris is not None:
            cam_state.auto_iris = real_auto_iris
    else:
        cam_state.iris = value
    cam_state.iris_f_number = await driver.query_f_number()
    await state.event_bus.publish("iris_changed", {"camera_id": camera_id, "value": cam_state.iris})


# --- Encoder function selection + turning ------------------------------
# Button 1 (Rec) cycles through this fixed list. `camera_status` is first,
# so before any button-1 press (app start, camera connect) it shows "Camera
# Info" -- every default-index lookup falls back to `.get(channel_index, 0)`.
_ENCODER_FUNCTIONS = ("camera_status", "gain", "pedestal", "nd")

_ENCODER_STEP_METHODS = {
    "gain": "step_gain",
    "pedestal": "step_pedestal",
    "nd": "set_nd",
}
_ENCODER_STATE_FIELDS = {
    "gain": "gain_db",
    "pedestal": "pedestal",
    "nd": "nd_index",
}
_ENCODER_ACCEL_WINDOW = 0.1  # >3 ticks per 100ms -> 5x acceleration
_ENCODER_ACCEL_THRESHOLD = 3
_ENCODER_ACCEL_MULTIPLIER = 5


def _encoder_multiplier(state: AppState, channel_index: int, now: float) -> int:
    history = state.encoder_tick_history.setdefault(channel_index, [])
    history[:] = [t for t in history if now - t < _ENCODER_ACCEL_WINDOW]
    history.append(now)
    return _ENCODER_ACCEL_MULTIPLIER if len(history) > _ENCODER_ACCEL_THRESHOLD else 1


def _encoder_value_range(driver: CameraDriver | None, function_name: str) -> tuple[int, int] | None:
    """Value range for `gain`/`pedestal` from the connected driver, which is
    model-dependent. `None` means either no driver or a model without a
    known range for this function -- no invented fallback. `gain`'s upper
    bound is `effective_gain_max_db` rather than the static `gain_max_db`:
    on models with super-gain coupling it's lower until super gain is
    confirmed on."""
    if function_name == "gain":
        lo = getattr(driver, "gain_min_db", None)
        hi = getattr(driver, "effective_gain_max_db", None)
    elif function_name == "pedestal":
        lo, hi = getattr(driver, "pedestal_min", None), getattr(driver, "pedestal_max", None)
    else:
        return None
    if lo is None or hi is None:
        return None
    return (lo, hi)


async def cycle_encoder_function(state: AppState, channel_index: int) -> str | None:
    """Button 1 (Rec): cycles locally through `_ENCODER_FUNCTIONS`, sending
    no camera command itself. `camera_status` is a pure display entry with
    no step method/state field -- shows camera name + iris instead of a
    function value.

    Re-queries the new function's current value immediately on switch, so
    the next turn starts from the real camera value rather than a stale
    local one. Also resets the "saved" display flag and any pending delta
    left over from the previous function."""
    new_index = (state.encoder_function_index.get(channel_index, -1) + 1) % len(_ENCODER_FUNCTIONS)
    state.encoder_function_index[channel_index] = new_index
    function_name = _ENCODER_FUNCTIONS[new_index]
    state.encoder_pending_delta[channel_index] = 0
    state.encoder_saved[channel_index] = False
    LOGGER.info("Kanal %s: Encoder-Funktion -> %s", channel_index, function_name)

    entry = state.mapping.get_channel("fader", channel_index)
    if entry is not None:
        driver = state.drivers.get(entry.camera_id)
        field_name = _ENCODER_STATE_FIELDS.get(function_name)
        if driver is not None and driver.connected and field_name is not None:
            fresh = await driver.get_state()
            cam_state = state.state_store.get_camera(entry.camera_id)
            setattr(cam_state, field_name, getattr(fresh, field_name))

    await state.event_bus.publish(
        "feature_changed", {"channel_index": channel_index, "key": f"encoder:{function_name}"}
    )
    return function_name


async def apply_encoder_turn(state: AppState, channel_index: int, tick_delta: int) -> None:
    """Encoder turn for `gain`/`pedestal`/`nd`: sends the new value live to
    the camera on every tick, through `state.encoder_rate_limiters` so not
    every MIDI tick triggers its own HTTP request. A tick the limiter is
    holding back is not lost -- it accumulates in `encoder_pending_delta`
    and is replayed as a combined delta on the next allowed tick.

    `nd` is an ordered, model-dependent, sometimes-sparse value list
    (`driver.nd_options`) rather than a continuous range -- handled in its
    own branch below that operates on list positions, not raw data values,
    and clamps at the edges instead of wrapping.

    `tick_delta` is an already-decoded, signed delta (one "click"); the MIDI
    CC decoding lives in
    `midi.mackie.MackieControlProtocol.encoder_cc_to_delta`, the web UI
    supplies the delta directly. No effect without a connected camera, a
    known current value, or on `camera_status` (a display-only entry, not
    in `_ENCODER_STATE_FIELDS`).

    The proposed value is clamped to the same range as the UI display
    (`_encoder_value_range()`).

    A tick moves `gain` by `driver.gain_step_db` rather than always 1dB: the
    3dB-step models only accept multiples of 3dB, so a full step keeps the
    clamped value valid too. `pedestal` has no step field and stays at 1 per
    click.

    Every actual turn tick clears `encoder_saved` (the "saved" display only
    holds until the next turn)."""
    entry = state.mapping.get_channel("fader", channel_index)
    if entry is None:
        return
    function_name = _ENCODER_FUNCTIONS[state.encoder_function_index.get(channel_index, 0) % len(_ENCODER_FUNCTIONS)]
    field_name = _ENCODER_STATE_FIELDS.get(function_name)
    if field_name is None:
        return  # camera_status: display-only, no camera action
    camera_id = entry.camera_id
    driver = state.drivers.get(camera_id)
    if driver is None or not driver.connected:
        return

    state.encoder_saved[channel_index] = False

    now = time.monotonic()
    multiplier = _encoder_multiplier(state, channel_index, now)
    # Models with GAIN_STEP_DB > 1 only accept multiples of that step, so a
    # tick must move by a full step, not always 1dB. `pedestal` has no step
    # field and stays at 1.
    step = (getattr(driver, "gain_step_db", None) or 1) if function_name == "gain" else 1
    delta = tick_delta * multiplier * step
    pending = state.encoder_pending_delta.get(channel_index, 0) + delta

    cam_state = state.state_store.get_camera(camera_id)
    confirmed = getattr(cam_state, field_name, None)
    gain_auto = function_name == "gain" and cam_state.gain_auto
    if confirmed is None and not gain_auto:
        state.encoder_pending_delta[channel_index] = pending
        return

    step_method = getattr(driver, _ENCODER_STEP_METHODS[function_name], None)

    if gain_auto:
        # Gain is currently in Auto/AGC: no numeric current value, so no
        # rate-limiter/delta-clamping like below -- turning up (pending>0)
        # exits Auto, turning down stays in Auto (no lower state). Exiting
        # is proportional/accelerated like any other turn: `step_gain()`
        # treats Auto internally as a virtual position one step below
        # `gain_min_db` and lands at `gain_min_db + (pending-1)`, clamped to
        # `effective_gain_max_db`. Deliberately without a rate limiter --
        # the Auto<->manual transition is a rare boundary crossing, not
        # continuous dragging.
        if pending <= 0 or step_method is None:
            state.encoder_pending_delta[channel_index] = min(pending, 0)
            return
        try:
            new_db, new_auto = await step_method(pending)
        except CameraCommandError as exc:
            cam_state.error = str(exc)
            # A value rejected by the camera must not leave the pending
            # delta in place, or the next preview would show a value that
            # was never actually reached.
            state.encoder_pending_delta[channel_index] = 0
            await state.event_bus.publish("error", {"camera_id": camera_id, "message": str(exc)})
            return
        cam_state.gain_db = new_db
        cam_state.gain_auto = new_auto
        cam_state.error = None
        state.encoder_pending_delta[channel_index] = 0
        return

    if function_name == "nd":
        # ND is an ordered, sometimes-sparse value list, not a continuous
        # range -- `pending`/`confirmed` are list positions here, not raw
        # data values. Clamps at the edge (no wrap), unlike
        # `PanasonicAWDriver.cycle_nd()`, which still wraps for the
        # (not yet wired) mute-button use case.
        nd_options = getattr(driver, "nd_options", None) or []
        positions = [opt_index for opt_index, _ in nd_options]
        if not positions or confirmed not in positions:
            state.encoder_pending_delta[channel_index] = pending
            return
        current_position = positions.index(confirmed)
        proposed_position = max(0, min(len(positions) - 1, current_position + pending))
        proposed_index = positions[proposed_position]
        clamped_pending = proposed_position - current_position

        limiter = state.encoder_rate_limiters.get(camera_id)
        if limiter is None or step_method is None or not limiter.should_send(proposed_index):
            state.encoder_pending_delta[channel_index] = clamped_pending
            return
        try:
            await step_method(proposed_index)
        except CameraCommandError as exc:
            cam_state.error = str(exc)
            state.encoder_pending_delta[channel_index] = 0
            await state.event_bus.publish("error", {"camera_id": camera_id, "message": str(exc)})
            return
        cam_state.nd_index = proposed_index
        cam_state.error = None
        state.encoder_pending_delta[channel_index] = 0
        return

    value_range = _encoder_value_range(driver, function_name)
    proposed = confirmed + pending
    if value_range is not None:
        # Don't clamp gain to the minimum on underflow -- turning down
        # further switches to Auto instead (see PanasonicAWDriver.step_gain());
        # the upper bound stays clamped.
        if not (function_name == "gain" and proposed < value_range[0]):
            proposed = max(value_range[0], min(value_range[1], proposed))

    limiter = state.encoder_rate_limiters.get(camera_id)
    if limiter is None or step_method is None or not limiter.should_send(proposed):
        state.encoder_pending_delta[channel_index] = proposed - confirmed
        return

    try:
        result = await step_method(proposed - confirmed)
    except CameraCommandError as exc:
        cam_state.error = str(exc)
        # A value rejected by the camera must not leave the pending delta
        # in place, or the next preview would show an unreachable value.
        state.encoder_pending_delta[channel_index] = 0
        await state.event_bus.publish("error", {"camera_id": camera_id, "message": str(exc)})
        return
    if function_name == "gain":
        new_db, new_auto = result
        cam_state.gain_db = new_db
        cam_state.gain_auto = new_auto
    else:
        setattr(cam_state, field_name, result)
    cam_state.error = None
    state.encoder_pending_delta[channel_index] = 0
    # No "feature_changed" event here (unlike commit_encoder_value below):
    # that would trigger a full scribble-strip refresh on every turn tick.
    # Callers update the display directly instead.


async def commit_encoder_value(state: AppState, channel_index: int) -> None:
    """Encoder push: since values are sent live on every turn, this is
    purely visual feedback -- the camera value is already current, so no
    additional command is sent. Only marks the channel as "saved"
    (`encoder_saved`) until the next turn tick. No effect on
    `camera_status` or without an assigned camera."""
    entry = state.mapping.get_channel("fader", channel_index)
    if entry is None:
        return
    function_name = _ENCODER_FUNCTIONS[state.encoder_function_index.get(channel_index, 0) % len(_ENCODER_FUNCTIONS)]
    if function_name not in _ENCODER_STEP_METHODS:
        return
    state.encoder_saved[channel_index] = True
    await state.event_bus.publish(
        "feature_changed", {"channel_index": channel_index, "key": f"encoder:{function_name}"}
    )


def encoder_preview(state: AppState, channel_index: int) -> tuple[str, int | None] | None:
    """Active encoder function + current value (last confirmed camera value
    plus any delta still held back by the rate limiter) for the scribble
    strip and web UI. `None` if the active function is a display-only entry
    with no state field (e.g. `camera_status`) or the current value isn't
    known yet. The value itself is `None` when `gain` is in Auto/AGC --
    still returns a tuple so line 1 keeps showing "GAIN", with the `None`
    value rendered as "AUTO" by the callers. For `nd`, the returned value is
    the raw data value of the target position, not the list position itself
    (`encoder_pending_delta` counts list positions for `nd`)."""
    function_name = _ENCODER_FUNCTIONS[state.encoder_function_index.get(channel_index, 0) % len(_ENCODER_FUNCTIONS)]
    field_name = _ENCODER_STATE_FIELDS.get(function_name)
    if field_name is None:
        return None
    entry = state.mapping.get_channel("fader", channel_index)
    if entry is None:
        return None
    cam_state = state.state_store.get_camera(entry.camera_id)
    if function_name == "gain" and cam_state.gain_auto:
        return function_name, None
    confirmed = getattr(cam_state, field_name, None)
    if confirmed is None:
        return None
    if function_name == "nd":
        driver = state.drivers.get(entry.camera_id)
        nd_options = getattr(driver, "nd_options", None) or []
        positions = [opt_index for opt_index, _ in nd_options]
        if confirmed not in positions:
            return None
        current_position = positions.index(confirmed)
        pending = state.encoder_pending_delta.get(channel_index, 0)
        proposed_position = max(0, min(len(positions) - 1, current_position + pending))
        return function_name, positions[proposed_position]
    return function_name, confirmed + state.encoder_pending_delta.get(channel_index, 0)


def _encoder_function_unsupported(state: AppState, channel_index: int) -> str | None:
    """Returns the active function name if it's `gain`/`pedestal`/`nd` and
    the connected camera model has no data for it at all (e.g. a model with
    no physical ND filter); otherwise `None`. Distinguishes "not supported
    by this model" from "value just not known yet" (camera not connected,
    AGC active) -- the latter still falls back to the previous iris%/camera
    name display."""
    function_name = _ENCODER_FUNCTIONS[state.encoder_function_index.get(channel_index, 0) % len(_ENCODER_FUNCTIONS)]
    if function_name not in _ENCODER_STATE_FIELDS:
        return None
    entry = state.mapping.get_channel("fader", channel_index)
    if entry is None:
        return None
    driver = state.drivers.get(entry.camera_id)
    if driver is None:
        return None
    if function_name == "nd":
        if getattr(driver, "nd_options", None):
            return None
        return function_name
    if _encoder_value_range(driver, function_name) is not None:
        return None
    return function_name


def _nd_label(driver: CameraDriver | None, index: int | None) -> str | None:
    """Label for ND filter data value `index` from `driver.nd_options`
    (e.g. "1/64") -- `None` if `index` is unknown or the driver has no ND
    catalog."""
    if index is None:
        return None
    nd_options = getattr(driver, "nd_options", None) or []
    for opt_index, label in nd_options:
        if opt_index == index:
            return label
    return None


def _encoder_value_text(function_name: str, value: int | None) -> str:
    """Compact display of the active encoder value (7-character scribble
    strip limit). No function prefix -- line 1 already shows the function
    name. `gain` is the only one with a physical unit (dB); `pedestal` is a
    unitless raw value. `value` is `None` when `gain` is in Auto/AGC, shown
    as "AUTO" instead of a dB value."""
    if value is None:
        return "AUTO"
    suffix = "dB" if function_name == "gain" else ""
    return f"{value:+d}{suffix}"


def channel_display_text(state: AppState, channel_index: int) -> str:
    """Line 2 of the channel display -- the physical scribble strip and the
    web UI show exactly this same value through the same function. For
    `camera_status` this is the iris F-number, for `gain`/`pedestal` the
    function value (see `encoder_preview`), for `nd` the label of the
    target data value -- or "n/a" if the model doesn't support this
    function at all, or the F-number isn't known yet."""
    preview = encoder_preview(state, channel_index)
    if preview is None:
        if _encoder_function_unsupported(state, channel_index) is not None:
            return "n/a"
        entry = state.mapping.get_channel("fader", channel_index)
        cam_state = state.state_store.get_camera(entry.camera_id) if entry is not None else None
        f_number = cam_state.iris_f_number if cam_state is not None else None
        return f_number if f_number is not None else "n/a"
    function_name, value = preview
    if function_name == "nd":
        entry = state.mapping.get_channel("fader", channel_index)
        driver = state.drivers.get(entry.camera_id) if entry is not None else None
        return _nd_label(driver, value) or "n/a"
    return _encoder_value_text(function_name, value)


def channel_line1_text(state: AppState, channel_index: int, camera_name: str | None) -> str:
    """Line 1 of the channel display -- the camera name for `camera_status`,
    otherwise the function name (GAIN/PEDESTAL/...) so it's clear what the
    value in line 2 refers to. Shows the function name even when the model
    doesn't support it, so line 2's "n/a" has a visible label."""
    preview = encoder_preview(state, channel_index)
    if preview is None:
        unsupported = _encoder_function_unsupported(state, channel_index)
        if unsupported is not None:
            return unsupported.upper()
        return camera_name or ""
    function_name, _ = preview
    return function_name.upper()


def _channel_encoder_snapshot(state: AppState, index: int) -> dict:
    """Encoder state for the web UI, which can also drive the encoder
    directly. `value` is `None` for `camera_status` (display-only); the web
    UI then shows name+iris via `channel_display_text`. `saved` drives the
    "saved" feedback after an encoder push, until the next turn tick."""
    function_name = _ENCODER_FUNCTIONS[state.encoder_function_index.get(index, 0) % len(_ENCODER_FUNCTIONS)]
    preview = encoder_preview(state, index)
    value = preview[1] if preview is not None else None
    entry = state.mapping.get_channel("fader", index)
    driver = state.drivers.get(entry.camera_id) if entry is not None else None
    value_range = _encoder_value_range(driver, function_name)
    return {
        "function": function_name,
        "value": value,
        "saved": state.encoder_saved.get(index, False),
        "min": value_range[0] if value_range else None,
        "max": value_range[1] if value_range else None,
    }


def available_button_features(state: AppState, camera_id: str) -> dict[str, str]:
    """Feature catalog (`key -> label`) for the Setup page dropdowns. Empty
    if the driver/detected camera model offers no catalog."""
    driver = state.drivers.get(camera_id)
    if driver is None:
        return {}
    return dict(getattr(driver, "BUTTON_FEATURE_LABELS", {}))


async def assign_channel_button(
    state: AppState, channel_index: int, button_slot: str, feature_key: str | None
) -> None:
    """Persists a channel's button 2/3 feature assignment to `config.yaml`.
    `feature_key=None`/empty clears the assignment.

    When assigning a toggle feature with a known query command, immediately
    queries its current state so the button shows the correct lit/unlit
    state in the web UI right away, instead of only after the first press."""
    if button_slot not in ("button2", "button3"):
        raise ValueError(f"ungültiger Button-Slot: {button_slot!r}")
    channel_cfg = _channel_config(state, channel_index)
    if channel_cfg is None:
        raise ValueError(f"Kanal {channel_index} hat keine Kamera zugewiesen")
    if feature_key:
        channel_cfg.buttons[button_slot] = feature_key
    else:
        channel_cfg.buttons.pop(button_slot, None)
    save_config(state.config_path, state.config)

    if feature_key:
        entry = state.mapping.get_channel("fader", channel_index)
        if entry is not None:
            driver = state.drivers.get(entry.camera_id)
            if driver is not None and driver.connected:
                query_button_feature = getattr(driver, "query_button_feature", None)
                if query_button_feature is not None:
                    known_state = await query_button_feature(feature_key)
                    if known_state is not None:
                        cam_state = state.state_store.get_camera(entry.camera_id)
                        cam_state.feature_states[feature_key] = known_state

    await state.event_bus.publish("config_changed", {"channel_index": channel_index})


async def apply_button_action(state: AppState, channel_index: int, button_slot: str) -> None:
    """Fires the camera feature action assigned to a channel button. No
    effect without a camera/assignment/connection -- matches physical
    behavior (an unassigned button does nothing).

    Only "toggle"/"trigger" feature kinds exist: multi-value camera
    parameters (knee, DRS) are modeled as one toggle per target state
    rather than a cycling feature, since button 2/3 only have a single,
    non-multicolor LED and can only show on/off. A toggle can list
    `exclusive_with` sibling keys (e.g. AW-UE160's `knee_manual`/
    `knee_auto`): turning one on locally clears the others, since the
    camera only has one active state for the group."""
    if button_slot not in ("button2", "button3"):
        raise ValueError(f"ungültiger Button-Slot: {button_slot!r}")
    entry = state.mapping.get_channel("fader", channel_index)
    if entry is None:
        return
    camera_id = entry.camera_id
    driver = state.drivers.get(camera_id)
    if driver is None or not driver.connected:
        return
    channel_cfg = _channel_config(state, channel_index)
    feature_key = channel_cfg.buttons.get(button_slot) if channel_cfg else None
    if not feature_key:
        return
    feature = getattr(driver, "BUTTON_FEATURES", {}).get(feature_key)
    if feature is None:
        return
    cam_state = state.state_store.get_camera(camera_id)
    try:
        if feature["kind"] == "toggle":
            new_enabled = not bool(cam_state.feature_states.get(feature_key, False))
            await driver.trigger_button_feature(feature_key, enabled=new_enabled)
            cam_state.feature_states[feature_key] = new_enabled
            if new_enabled:
                for sibling in feature.get("exclusive_with", []):
                    cam_state.feature_states[sibling] = False
            if feature_key == "auto_iris":
                # apply_iris()'s snapback logic checks cam_state.auto_iris,
                # not feature_states, so it needs to be kept in sync here too.
                cam_state.auto_iris = new_enabled
            LOGGER.info("Kanal %s: %s -> %s", channel_index, feature_key, "on" if new_enabled else "off")
        else:  # "trigger"
            await driver.trigger_button_feature(feature_key)
            LOGGER.info("Kanal %s: %s ausgeloest", channel_index, feature_key)
    except CameraCommandError as exc:
        cam_state.error = str(exc)
        await state.event_bus.publish("error", {"camera_id": camera_id, "message": str(exc)})
        return
    cam_state.error = None
    await state.event_bus.publish("feature_changed", {"camera_id": camera_id, "key": feature_key})


def channel_snapshot(state: AppState) -> list[dict]:
    """One entry per channel strip (1-8). Channels without an assigned
    camera have `camera_id: None` and aren't controllable in the UI."""
    fader_channels = state.mapping.channels_for_type("fader")
    channels = []
    for index in range(1, 9):
        entry = fader_channels.get(index)
        camera_id = entry.camera_id if entry else None
        camera_cfg = state.cameras.get(camera_id) if camera_id else None
        cam_state = state.state_store.get_camera(camera_id) if camera_id else None
        driver = state.drivers.get(camera_id) if camera_id else None
        channels.append(
            {
                "index": index,
                "camera_id": camera_id,
                "name": camera_cfg.name if camera_cfg else None,
                "host": camera_cfg.host if camera_cfg else None,
                "port": camera_cfg.port if camera_cfg else None,
                "model": driver.model if driver else None,
                "connected": driver.connected if driver else False,
                "iris": cam_state.iris if cam_state else None,
                "gain_db": cam_state.gain_db if cam_state else None,
                "auto_iris": cam_state.auto_iris if cam_state else None,
                "error": cam_state.error if cam_state else None,
                "buttons": _channel_button_snapshot(state, index, driver, cam_state),
                "companion": _channel_companion_snapshot(state, index),
                "encoder": _channel_encoder_snapshot(state, index),
                "display_line1": channel_line1_text(state, index, camera_cfg.name if camera_cfg else None),
                "display_text": channel_display_text(state, index),
            }
        )
    return channels


def _channel_companion_snapshot(state: AppState, index: int) -> dict | None:
    channel_cfg = _channel_config(state, index)
    target = channel_cfg.companion if channel_cfg else None
    if target is None:
        return None
    return {"page": target.page, "row": target.row, "column": target.column}


def _channel_button_snapshot(state: AppState, index: int, driver, cam_state) -> dict:
    """Button 2/3 assignment + last tracked state for a channel."""
    channel_cfg = _channel_config(state, index)
    labels = getattr(driver, "BUTTON_FEATURE_LABELS", {}) if driver else {}
    result: dict[str, dict | None] = {}
    for slot in ("button2", "button3"):
        key = channel_cfg.buttons.get(slot) if channel_cfg else None
        if not key:
            result[slot] = None
            continue
        result[slot] = {
            "key": key,
            "label": labels.get(key, key),
            "state": cam_state.feature_states.get(key) if cam_state else None,
        }
    return result
