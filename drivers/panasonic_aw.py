from __future__ import annotations

from collections.abc import Callable

import httpx

from core.state import CameraState
from drivers.base import CameraCommandError, CameraDriver

# --- Iris (#AXI / #GI, §7.2): normalisiert 0.0-1.0 <-> 555h-FFFh, linear (Spec-Formel) ---
_IRIS_DATA_MIN = 0x555
_IRIS_DATA_MAX = 0xFFF

# --- Gain (OGU/QGU, §7.2): 02h(-6dB)-08h(0dB)-14h(+12dB) -> Data = 0x08 + db (aus den
# drei gegebenen Ankerpunkten linear hergeleitet: 08-02=6, 14-08=0C=12, je 1 Hex-Step = 1 dB) ---
_GAIN_ZERO_DB_DATA = 0x08
_GAIN_MIN_DB = -6
_GAIN_MAX_DB = 12
_GAIN_AGC_DATA = 0x80

# --- Master Pedestal (OSJ:0F, §7.2): 738h(-200)-800h(0)-8C8h(+200) -> Data = 0x800 + value ---
_PEDESTAL_CENTER_DATA = 0x800

# --- R/B Gain Preset (OSL:36/38, §7.2): 418h(-1000)-800h(0)-BE8h(+1000) -> Data = 0x800 + value ---
_RB_GAIN_CENTER_DATA = 0x800

_ND_INDICES = (0, 1, 2, 3)  # THROUGH, 1/4, 1/16, 1/64 (OFT:[0-3], §7.2)
_SHUTTER_MODES = {"off": 0, "step": 1, "synchro": 2, "elc": 3}  # OSJ:03:[0-3], §7.2

_ERROR_PREFIXES_CAM = ("ER1:", "ER2:", "ER3:")
_ERROR_PREFIXES_PTZ = ("eR1", "eR2", "eR3")
_ERROR_STATE_PREFIXES = ("rER", "OER")  # laut CameraState-Docstring in Spec §6

_REQUEST_TIMEOUT = 1.5  # §7.4: Default 1,5s Timeout, 1 Retry


def _iris_to_data(value: float) -> int:
    return _IRIS_DATA_MIN + round(value * (_IRIS_DATA_MAX - _IRIS_DATA_MIN))


def _data_to_iris(data: int) -> float:
    return (data - _IRIS_DATA_MIN) / (_IRIS_DATA_MAX - _IRIS_DATA_MIN)


def _extract_value(body: str) -> str | None:
    """Wert nach dem letzten ':' — durchgängiges Antwortmuster der Befehlstabelle
    (z. B. 'OGU:08' -> '08', 'OID:AW-UE160' -> 'AW-UE160')."""
    if not body or ":" not in body:
        return None
    value = body.rsplit(":", 1)[-1].strip()
    return value or None


class PanasonicAWDriver(CameraDriver):
    """AW-Serie (Referenz AW-UE160) über CGI/HTTP, §7 der Spec.

    Notification-Feedback-Kanal (§7.3: Update-Notifications, #LPC1 Lens-Info,
    QSV-Heartbeat) ist hier NICHT implementiert — das ist ein eigener,
    separater Arbeitsschritt (async TCP-Listener). subscribe() speichert
    Callbacks nur für spätere Verwendung, feuert aktuell nichts.
    """

    # Kamera-Feature-Buttons (Spec §9a: Button-2/3-Aktionen kommen aus der
    # pro Kameramodell verifizierten UI_BUTTONS/UI_BUTTON_LABELS-Definition
    # des externen Referenzprojekts smart-reset-browser, nicht aus einer
    # festen Liste in diesem Tool). Wörtlich portiert aus
    # C:\smart-reset-browser\camera_plugins\panasonic\aw_ue160.py
    # (UI_BUTTONS/UI_BUTTON_LABELS), dort laut deren CLAUDE.md gegen reale
    # Panasonic-Interface-Specs verifiziert. NICHT unabhängig gegen die
    # lokalen PDF-Referenzen (docs/specs/) nachverifiziert — PDF-Rendering
    # (poppler/pdftoppm) war in dieser Umgebung nicht verfügbar.
    #
    # "toggle": on/off-Kommando, kein Query verfügbar (auch in der
    #   Referenzquelle nicht — Zustand wird dort wie hier nur lokal
    #   getrackt, nicht kamera-verifiziert, siehe core/state.py).
    # "trigger": ein einmaliges Kommando, kein Ein/Aus-Zustand.
    # "cycle": mehrere benannte Schritte, jeder Schritt kann mehrere
    #   Kommandos umfassen (z. B. "knee").
    BUTTON_FEATURES: dict[str, dict] = {
        "auto_focus":    {"kind": "toggle", "on": "OAF:1", "off": "OAF:0"},
        "auto_iris":     {"kind": "toggle", "on": "ORS:1", "off": "ORS:0"},
        "awb_black":     {"kind": "trigger", "cmd": "OAS"},
        "aww_white":     {"kind": "trigger", "cmd": "OWS"},
        "drs":           {"kind": "toggle", "on": "OSA:0D:1", "off": "OSA:0D:0"},
        "flare":         {"kind": "toggle", "on": "OSA:11:1", "off": "OSA:11:0"},
        "gamma":         {"kind": "toggle", "on": "OSA:0A:1", "off": "OSA:0A:0"},
        "knee": {
            "kind": "cycle",
            "cycle": [
                {"label": "OFF", "cmd": ["OSL:45:0"]},
                {"label": "Manual", "cmd": ["OSL:45:1", "OSA:2D:1"]},
                {"label": "Auto", "cmd": ["OSL:45:1", "OSA:2D:2"]},
            ],
        },
        "linear_matrix": {"kind": "toggle", "on": "OSL:6C:1", "off": "OSL:6C:0"},
        "matrix":        {"kind": "toggle", "on": "OSA:84:1", "off": "OSA:84:0"},
        "osd":           {"kind": "toggle", "on": "DUS:1", "off": "DUS:0"},
        "white_clip":    {"kind": "toggle", "on": "OSA:2E:1", "off": "OSA:2E:0"},
    }

    BUTTON_FEATURE_LABELS: dict[str, str] = {
        "auto_focus": "Auto Focus",
        "auto_iris": "Auto Iris",
        "drs": "DRS",
        "flare": "Flare",
        "gamma": "Gamma",
        "knee": "Knee",
        "linear_matrix": "Linear Matrix",
        "matrix": "Matrix",
        "osd": "OSD",
        "white_clip": "White Clip",
        "awb_black": "ABB (Black)",
        "aww_white": "AWW (White)",
    }

    def __init__(self, host: str, port: int = 80) -> None:
        self.host = host
        self.port = port
        self.model: str | None = None
        self._connected = False
        self._client: httpx.AsyncClient | None = None
        self._callbacks: list[Callable[[dict], None]] = []

    # --- Lifecycle -----------------------------------------------------

    async def connect(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=f"http://{self.host}:{self.port}", timeout=_REQUEST_TIMEOUT
        )
        self.model = await self._query_model()
        self._connected = self.model is not None

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    # --- Steuerung -------------------------------------------------------

    async def set_iris(self, value: float) -> None:
        data = _iris_to_data(value)
        await self._request("aw_ptz", f"#AXI{data:03X}")

    async def set_auto_iris(self, on: bool) -> None:
        await self._request("aw_cam", f"ORS:{1 if on else 0}")

    async def set_gain_db(self, db: int) -> None:
        data = _GAIN_ZERO_DB_DATA + db
        await self._request("aw_cam", f"OGU:{data:02X}")

    async def step_gain(self, delta_db: int) -> int:
        current = await self._query_gain_db()
        if current is None:
            # AGC aktiv (80h) oder nicht lesbar — Spec §7.2: Steps ignorieren,
            # Solo-LED blinken lassen ist Mapping-Engine-Aufgabe, nicht Treiber.
            raise CameraCommandError(
                "gain step ignored: AGC active or gain unreadable",
                command="OGU",
            )
        new_db = max(_GAIN_MIN_DB, min(_GAIN_MAX_DB, current + delta_db))
        await self.set_gain_db(new_db)
        return new_db

    async def set_pedestal(self, value: int) -> None:
        data = _PEDESTAL_CENTER_DATA + value
        await self._request("aw_cam", f"OSJ:0F:{data:03X}")

    async def set_rb_gain(self, r: int | None, b: int | None) -> None:
        if r is not None:
            data = _RB_GAIN_CENTER_DATA + r
            await self._request("aw_cam", f"OSL:36:{data:03X}")
        if b is not None:
            data = _RB_GAIN_CENTER_DATA + b
            await self._request("aw_cam", f"OSL:38:{data:03X}")

    async def set_nd(self, index: int) -> None:
        if index not in _ND_INDICES:
            raise ValueError(f"ND index out of range: {index}")
        await self._request("aw_cam", f"OFT:{index}")

    async def cycle_nd(self) -> int:
        current = await self._query_nd()
        new_index = ((current + 1) % 4) if current is not None else 0
        await self.set_nd(new_index)
        return new_index

    async def set_shutter(self, mode: str, value: int | None) -> None:
        mode_key = mode.lower()
        if mode_key not in _SHUTTER_MODES:
            raise ValueError(f"unknown shutter mode: {mode}")
        await self._request("aw_cam", f"OSJ:03:{_SHUTTER_MODES[mode_key]}")
        if value is not None:
            # Data = Verschlusszeit-Nenner direkt als Hex (z.B. 0x3C=60 -> 1/60), bestaetigt
            # in AW-UE160_InterfaceSpecification_E.pdf Kap.9 "SHUTTER SPEED" (S.50). Nur
            # bestimmte Nenner je aktivem Videoformat zulaessig (sonst ER3) -- siehe Spec
            # §14 Punkt 11; keine Format-abhaengige Validierung hier. Diese OSJ:03/OSJ:06
            # Kodierung gilt nur fuer die UE160/UE150-Befehlsfamilie, nicht fuer andere
            # AW-Modelle (die nutzen OSH bzw. OSG:5D mit eigener Enum-Tabelle).
            await self._request("aw_cam", f"OSJ:06:{value:04X}")

    async def trigger_awb(self) -> None:
        await self._request("aw_cam", "OWS")

    async def set_bars(self, on: bool) -> None:
        await self._request("aw_cam", f"DCB:{1 if on else 0}")

    async def recall_preset(self, number: int) -> None:
        if not 0 <= number <= 99:
            raise ValueError(f"preset number out of range: {number}")
        await self._request("aw_ptz", f"#R{number:02d}")

    # --- Kamera-Feature-Buttons (§9a, Katalog: BUTTON_FEATURES) -----------
    # Kein Teil der CameraDriver-ABC (Spec §6 bleibt unveraendert) -- die
    # Anwendungsschicht greift nur ueber getattr(driver, "BUTTON_FEATURES", {})
    # zu, ein Treiber ohne Katalog bietet dann einfach keine Optionen an.

    async def trigger_button_feature(self, key: str, *, enabled: bool | None = None) -> None:
        """Toggle (braucht `enabled`) oder Trigger (ignoriert `enabled`).
        `auto_iris`/`aww_white` delegieren an die vorhandenen typisierten
        Methoden, um Kommando-Logik nicht doppelt zu halten."""
        if key == "auto_iris":
            if enabled is None:
                raise ValueError("'auto_iris' ist ein Toggle, 'enabled' erforderlich")
            await self.set_auto_iris(enabled)
            return
        if key == "aww_white":
            await self.trigger_awb()
            return
        feature = self.BUTTON_FEATURES.get(key)
        if feature is None:
            raise ValueError(f"unbekanntes Button-Feature: {key!r}")
        if feature["kind"] == "toggle":
            if enabled is None:
                raise ValueError(f"{key!r} ist ein Toggle, 'enabled' erforderlich")
            await self._request("aw_cam", feature["on"] if enabled else feature["off"])
        elif feature["kind"] == "trigger":
            await self._request("aw_cam", feature["cmd"])
        else:
            raise ValueError(f"{key!r} ist kein Toggle/Trigger, cycle_button_feature() nutzen")

    async def cycle_button_feature(self, key: str, target_index: int) -> None:
        feature = self.BUTTON_FEATURES.get(key)
        if feature is None or feature["kind"] != "cycle":
            raise ValueError(f"{key!r} ist kein Cycle-Feature")
        steps = feature["cycle"]
        if not 0 <= target_index < len(steps):
            raise ValueError(f"cycle index out of range: {target_index}")
        for cmd in steps[target_index]["cmd"]:
            await self._request("aw_cam", cmd)

    # --- Status ----------------------------------------------------------

    async def get_state(self) -> CameraState:
        iris, auto_iris = await self._query_iris()
        return CameraState(
            iris=iris,
            iris_f_number=await self._query_f_number(),
            auto_iris=auto_iris,
            gain_db=await self._query_gain_db(),
            nd_index=await self._query_nd(),
            shutter=None,  # Query-Response-Format fuer Shutter-Status nicht in Spec definiert
            bars=None,  # QBR-Response-Format nicht in Spec definiert (nur Query-Name, §11)
            error=await self._query_error(),
        )

    def subscribe(self, callback: Callable[[dict], None]) -> None:
        self._callbacks.append(callback)

    # --- interne Query-Helfer (§11: #GI, QIF, QGU, QFT, QRS, QBR) ---------

    async def _query_model(self) -> str | None:
        try:
            body = await self._request("aw_cam", "QID")
        except CameraCommandError:
            return None
        return _extract_value(body)

    async def _query_iris(self) -> tuple[float | None, bool | None]:
        try:
            body = await self._request("aw_ptz", "#GI")
        except CameraCommandError:
            return None, None
        # Antwortformat gi[Pos][Mode]: "gi" + 3 Hex-Digits Pos + 1 Hex-Digit Mode (§7.2)
        if len(body) < 6 or not body.lower().startswith("gi"):
            return None, None
        try:
            pos = int(body[2:5], 16)
            mode = int(body[5:6], 16)
        except ValueError:
            return None, None
        return _data_to_iris(pos), (mode == 1)

    async def _query_f_number(self) -> str | None:
        # OIF-Data->F-Nummer-Dekodiertabelle ist in der Spec nicht vollstaendig
        # reproduziert (nur Ankerpunkte 0Eh=F1.4, A0h=F16, FFh=CLOSE genannt, §7.2).
        # Ohne die vollstaendige Tabelle wird hier bewusst nicht dekodiert.
        try:
            body = await self._request("aw_cam", "QIF")
        except CameraCommandError:
            return None
        return _extract_value(body)

    async def _query_gain_db(self) -> int | None:
        # QGU als Query-Kommando ist laut Spec §14 Punkt 2 unbestaetigt.
        try:
            body = await self._request("aw_cam", "QGU")
        except CameraCommandError:
            return None
        value = _extract_value(body)
        if value is None:
            return None
        data = int(value, 16)
        if data == _GAIN_AGC_DATA:
            return None
        return data - _GAIN_ZERO_DB_DATA

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

    # --- HTTP-Transport (§7.1, §7.4) --------------------------------------

    async def _request(self, endpoint: str, cmd: str) -> str:
        if self._client is None:
            raise CameraCommandError("not connected", command=cmd)

        encoded_cmd = cmd.replace("#", "%23")
        url = f"/cgi-bin/{endpoint}?cmd={encoded_cmd}&res=1"

        try:
            response = await self._client.get(url)
        except httpx.TimeoutException:
            try:
                response = await self._client.get(url)  # §7.4: 1 Retry
            except httpx.HTTPError as exc:
                self._connected = False
                raise CameraCommandError(
                    f"timeout: {cmd}", command=cmd
                ) from exc
        except httpx.HTTPError as exc:
            self._connected = False
            raise CameraCommandError(
                f"connection error: {cmd}: {exc}", command=cmd
            ) from exc

        body = response.text.strip()
        error_prefixes = (
            _ERROR_PREFIXES_PTZ if endpoint == "aw_ptz" else _ERROR_PREFIXES_CAM
        )
        if body.startswith(error_prefixes):
            raise CameraCommandError(
                f"camera error for '{cmd}': {body}", command=cmd, response=body
            )
        return body
