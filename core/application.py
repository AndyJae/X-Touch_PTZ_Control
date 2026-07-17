"""core/application.py -- Anwendungsschicht (Spec §3 Core-Bausteine).

Verdrahtet Config/Treiber/Mapping-Engine/Rate-Limiter/EventBus zu einem
laufenden Prozess-Zustand (`AppState`) und stellt die Use-Cases bereit, die
ein Interface (Web-UI heute, X-Touch/MIDI später) aufruft: `connect_camera`,
`apply_iris`, `channel_snapshot`, `register_camera`. Kennt FastAPI nur an
der schmalen Stelle, an der tatsächlich WebSocket-Clients benachrichtigt
werden (`AppState.broadcast`) -- Routing/Templates gehören nicht hierher,
siehe `web/app.py`. Eine weitere Abstraktionsschicht für den einen
Broadcast-Mechanismus, den es gibt, wäre an dieser Stelle spekulativ.
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
    CompanionTarget,
    save_config,
)
from core.mapping import MappingEngine, build_mapping_from_config
from core.ratelimit import RateLimiter
from core.state import StateStore
from drivers.base import CameraCommandError, CameraDriver
from drivers.panasonic_aw import PanasonicAWDriver

LOGGER = logging.getLogger("ptz_control.application")

# Iris-Hysterese: 1 Digit der Geraete-Zielrange (555h-FFFh -> 2730 Schritte),
# Spec §8 "Nur bei Wertaenderung senden (Delta-Filter, Hysterese 1 Digit der
# Zielrange)".
_IRIS_HYSTERESIS = 1.0 / (0xFFF - 0x555)


def build_driver(camera: CameraConfig) -> CameraDriver:
    if camera.driver != "panasonic_aw":
        raise ValueError(f"unsupported driver: {camera.driver!r} (v1: nur panasonic_aw)")
    return PanasonicAWDriver(host=camera.host, port=camera.port)


@dataclass
class AppState:
    """Pro-Prozess-Zustand, an `app.state.ptz` gehaengt (Spec §3 Core-Bausteine)."""

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
    # Encoder-Funktionsauswahl je Kanal (Spec §9, Button 1/physisch Rec) --
    # Index in `config.channel_defaults.encoder.functions`, rein lokaler
    # Laufzeitzustand wie `feature_states` (siehe CameraState), nicht
    # persistiert.
    encoder_function_index: dict[int, int] = field(default_factory=dict)
    # Zeitstempel der letzten Encoder-Klicks je Kanal fuer die
    # Beschleunigungsregel unten (`_encoder_multiplier`).
    encoder_tick_history: dict[int, list[float]] = field(default_factory=dict)
    # Aufgelaufenes, noch NICHT an die Kamera gesendetes Delta je Kanal
    # (Nutzerentscheid: Drehen passt nur lokal an, erst Encoder-Push
    # committet, siehe `apply_encoder_turn`/`commit_encoder_value`).
    encoder_pending_delta: dict[int, int] = field(default_factory=dict)

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
    state = AppState(
        config=config,
        event_bus=EventBus(),
        state_store=StateStore(),
        mapping=build_mapping_from_config(config),
        cameras=cameras,
        drivers=drivers,
        rate_limiters=rate_limiters,
        config_path=config_path,
    )
    _subscribe_snapshot_broadcast(state)
    return state


def _subscribe_snapshot_broadcast(state: AppState) -> None:
    """Web-UI ist nur ein Consumer des EventBus, kein Sonderfall: reagiert auf
    Kamera-Domain-Events (`iris_changed`, `connection_changed`, `error`,
    `feature_changed`) mit einem vollen State-Broadcast an alle WS-Clients.
    Ein späterer MIDI-Consumer (Motorfader-/LED-Feedback, Spec §5.4) würde
    dieselben Topics abonnieren, ohne dass dieser Code angefasst werden
    müsste."""

    async def _on_camera_event(_payload: dict) -> None:
        await state.broadcast({"type": "snapshot", "channels": channel_snapshot(state)})

    for topic in ("iris_changed", "connection_changed", "error", "feature_changed", "config_changed"):
        state.event_bus.subscribe(topic, _on_camera_event)


def _channel_config(state: AppState, channel_index: int) -> BankChannelConfig | None:
    banks = state.config.banks
    if not banks:
        return None
    channels = banks[0].channels
    if not 1 <= channel_index <= len(channels):
        return None
    return channels[channel_index - 1]


def _wire_camera_events(state: AppState, camera_id: str, driver: CameraDriver) -> None:
    """Bruecke Treiber-Events (`subscribe()`, sync per ABC §6) auf den
    EventBus (async) -- damit reagieren Web-UI und MIDI-Motorfader auch auf
    Iris-Aenderungen, die nicht von PTZ_Control selbst ausgeloest wurden
    (z. B. Kamera-eigenes Web-UI), siehe `drivers/panasonic_aw.py`s
    Lens-Info-Feedback (§7.3)."""

    def on_event(event: dict) -> None:
        if event.get("type") == "iris_changed":
            state.state_store.get_camera(camera_id).iris = event["value"]
            asyncio.create_task(
                state.event_bus.publish("iris_changed", {"camera_id": camera_id, "value": event["value"]})
            )

    driver.subscribe(on_event)


async def connect_camera(state: AppState, camera_id: str) -> None:
    """Spec §11 Schritt 4: `connect()` -> `QID` -> `get_state()` (Vollabzug),
    danach Lens-Info-Feedback (§7.3) fuer Treiber, die das anbieten (wie
    BUTTON_FEATURES, §9a, kein Teil der CameraDriver-ABC -- Zugriff per
    hasattr(), ein Treiber ohne Unterstuetzung liefert dann einfach keine
    externen Iris-Updates)."""
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
        start_lens_feedback = getattr(driver, "start_lens_feedback", None)
        if start_lens_feedback is not None:
            try:
                await start_lens_feedback()
            except CameraCommandError as exc:
                LOGGER.warning("Kamera %s: Lens-Info-Feedback fehlgeschlagen: %s", camera_id, exc)
    finally:
        await state.event_bus.publish("connection_changed", {"camera_id": camera_id})


async def disconnect_camera(state: AppState, camera_id: str) -> None:
    """Trennt eine Kamera manuell (Setup-Tabelle: "Connect Camera" im
    verbundenen Zustand erneut geklickt -> Entkoppeln). Die Registrierung in
    `config.yaml` bleibt bestehen, nur die Laufzeitverbindung wird
    geschlossen -- ein erneutes "Connect Camera" verbindet wieder."""
    driver = state.drivers.get(camera_id)
    if driver is None:
        return
    await driver.disconnect()
    state.state_store.get_camera(camera_id).error = None
    await state.event_bus.publish("connection_changed", {"camera_id": camera_id})


async def register_camera(
    state: AppState, channel_index: int, *, name: str, host: str, port: int
) -> None:
    """Registriert/aktualisiert eine Kamera für einen Kanal über die
    Setup-Tabelle ("Connect Camera"-Button). Bewusste Abkehr von der
    ursprünglichen Spec-§10.3-Entscheidung "kein Formular-Editor" für
    Kamera-Stammdaten (Nutzerentscheid) -- die freie YAML-Ansicht aus §10.3
    ist davon nicht betroffen. Kamera-ID ist deterministisch `cam{channel}`,
    da die Tabelle kein eigenes ID-Feld hat; erneuter Aufruf für denselben
    Kanal aktualisiert damit dieselbe Kamera statt eine zweite anzulegen."""
    if not 1 <= channel_index <= 8:
        raise ValueError(f"Kanal außerhalb 1-8: {channel_index}")
    if not host:
        raise ValueError("Host darf nicht leer sein")
    camera_id = f"cam{channel_index}"

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
    state.mapping.set_channel("fader", channel_index, camera_id, state.config.channel_defaults.fader)

    await connect_camera(state, camera_id)  # verbindet + published "connection_changed"


async def rename_camera(state: AppState, channel_index: int, name: str) -> None:
    """Aktualisiert nur den Anzeigenamen einer bereits registrierten Kamera
    (Setup-Tabelle: Namensfeld verlassen) -- absichtlich unabhängig vom
    Connect/Disconnect-Toggle des "Connect Camera"-Buttons, damit Umbenennen
    keine bestehende Verbindung trennt. Kein Effekt, wenn der Kanal noch
    keine Kamera hat -- der Name wird dann erst beim nächsten "Connect
    Camera" mitgeschickt (siehe register_camera)."""
    entry = state.mapping.get_channel("fader", channel_index)
    if entry is None:
        return
    camera_cfg = state.cameras.get(entry.camera_id)
    if camera_cfg is None:
        return
    camera_cfg.name = name.strip() or f"CAM {channel_index}"
    save_config(state.config_path, state.config)
    await state.event_bus.publish("config_changed", {"channel_index": channel_index})


async def configure_companion(state: AppState, host: str, port: int) -> None:
    """Speichert die globale Bitfocus-Companion-Instanz (eine für alle
    Kanäle, Nutzerentscheid) -- Setup-Seite, Panel an der Stelle des
    ehemaligen "Camera Status"-Blocks."""
    state.config.companion.host = host.strip()
    state.config.companion.port = port
    save_config(state.config_path, state.config)
    await state.event_bus.publish("config_changed", {})


async def assign_channel_companion_target(
    state: AppState, channel_index: int, page: int | None, row: int | None, column: int | None
) -> None:
    """Speichert das SELECT-Button-Ziel (Companion Page/Row/Column) eines
    Kanals dauerhaft. `page/row/column=None` löscht die Zuordnung wieder
    (Muster: assign_channel_button)."""
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
    """Löst das SELECT-Button-Ziel eines Kanals in Companion aus (Spec §9,
    bewusste Erweiterung über v1 hinaus -- siehe Modul-Docstring
    core/companion.py). Kein Effekt ohne zugewiesenes Ziel. Wirft
    `CompanionError` bei Verbindungsfehler/Non-2xx weiter, damit die Route
    das dem Nutzer zurückmelden kann -- kein persistenter Fehlerzustand im
    Snapshot, SELECT ist eine einmalige Aktion ohne Dauerzustand."""
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


async def apply_iris(state: AppState, channel_index: int, value: float, *, final: bool) -> None:
    """Datenfluss Fader -> Kamera, Spec §3: Mapping -> Rate-Limiter -> Driver."""
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
    else:
        cam_state.iris = value
        cam_state.error = None
        await state.event_bus.publish("iris_changed", {"camera_id": camera_id, "value": value})


# --- Encoder-Funktionsauswahl + -Drehung (Spec §9) --------------------------
# Button 1 (physisch Rec) schaltet lokal durch `channel_defaults.encoder.
# functions`, der Encoder wendet Deltas auf die jeweils aktive Funktion an.
# Treiber-Methode je Funktion -- Erweiterung um weitere Funktionen (z. B.
# Shutter, siehe Spec §14 Punkt 8) braucht nur einen weiteren Eintrag hier
# und eine passende `step_*`-Methode im Treiber.
_ENCODER_STEP_METHODS = {
    "gain": "step_gain",
    "pedestal": "step_pedestal",
}
_ENCODER_STATE_FIELDS = {
    "gain": "gain_db",
    "pedestal": "pedestal",
}
# Nur fuer die UI-Anzeige (Knopf-Rotation, Wertebereich-Kontext) -- die
# tatsaechliche Begrenzung/Clamping bleibt allein Sache des Treibers
# (`_GAIN_MIN_DB`/`_GAIN_MAX_DB`/`_PEDESTAL_MIN`/`_PEDESTAL_MAX` in
# drivers/panasonic_aw.py), diese Kopie hier steuert nur die Darstellung.
_ENCODER_RANGES = {
    "gain": (-6, 12),
    "pedestal": (-200, 200),
}

_ENCODER_ACCEL_WINDOW = 0.1  # Spec §9: "Klicks/100 ms > 3 -> Beschleunigung x5"
_ENCODER_ACCEL_THRESHOLD = 3
_ENCODER_ACCEL_MULTIPLIER = 5


def _encoder_multiplier(state: AppState, channel_index: int, now: float) -> int:
    history = state.encoder_tick_history.setdefault(channel_index, [])
    history[:] = [t for t in history if now - t < _ENCODER_ACCEL_WINDOW]
    history.append(now)
    return _ENCODER_ACCEL_MULTIPLIER if len(history) > _ENCODER_ACCEL_THRESHOLD else 1


async def cycle_encoder_function(state: AppState, channel_index: int) -> str | None:
    """Button 1 (physisch Rec, Spec §9 "Encoder-Funktionsauswahl"): schaltet
    nur lokal weiter, sendet keinen Kamerabefehl. `channel_defaults.encoder.
    functions` enthaelt per Nutzerentscheid neben echten Parametern
    (`gain`/`pedestal`) auch `camera_status` als reinen Anzeige-Eintrag ohne
    Step-Methode/State-Feld -- Kamera-Name+Blende (Spec: "Camera Status")
    statt Funktion+Wert, siehe `encoder_preview()`/`_channel_encoder_snapshot()`.

    Fragt beim Wechsel zu einem echten Parameter sofort dessen Ist-Wert ab
    (Nutzerentscheid), damit die naechste Encoder-Drehung auf dem echten
    Kamerawert aufsetzt statt auf einem veralteten/lokalen Wert. Ein zweiter
    Button-1-Druck waehrend dieser Abfrage wartet implizit, da der
    MIDI-Rx-Poll-Loop Nachrichten sequenziell abarbeitet (siehe
    midi/fader.py `_poll_loop`).

    Ein noch nicht committeter Pending-Wert der zuvor aktiven Funktion wird
    dabei verworfen (Nutzerentscheid) -- Drehen aendert seit der
    Preview/Commit-Umstellung nur lokal, erst `commit_encoder_value()`
    (Encoder-Push) sendet tatsaechlich einen Kamerabefehl."""
    functions = state.config.channel_defaults.encoder.functions
    if not functions:
        return None
    current_index = state.encoder_function_index.get(channel_index, -1)
    new_index = (current_index + 1) % len(functions)
    state.encoder_function_index[channel_index] = new_index
    function_name = functions[new_index]
    state.encoder_pending_delta[channel_index] = 0

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
    """Encoder-Drehung -- passt NUR den lokalen Pending-Wert an, sendet
    keinen Kamerabefehl (Nutzerentscheid: erst `commit_encoder_value()`
    per Encoder-Push uebernimmt den Wert). `tick_delta` ist ein bereits
    dekodiertes, vorzeichenbehaftetes Delta (ein "Klick") -- die MIDI-CC-
    Dekodierung (Spec §5.2/§9: Wert 1-7 = +, 65-71 = -) lebt in
    `midi.mackie.MackieControlProtocol.encoder_cc_to_delta`, die Web-UI
    liefert das Delta direkt (siehe web/app.py WebSocket "encoder_turn").
    Kein Effekt ohne Kamera/Verbindung/vom Treiber unterstuetzte Funktion --
    insbesondere bei `camera_status` (reiner Anzeige-Eintrag, kein
    Step-Methoden-Eintrag in `_ENCODER_STEP_METHODS`)."""
    entry = state.mapping.get_channel("fader", channel_index)
    if entry is None:
        return
    functions = state.config.channel_defaults.encoder.functions
    if not functions:
        return
    function_name = functions[state.encoder_function_index.get(channel_index, 0) % len(functions)]
    if function_name not in _ENCODER_STEP_METHODS:
        return
    driver = state.drivers.get(entry.camera_id)
    if driver is None or not driver.connected:
        return

    multiplier = _encoder_multiplier(state, channel_index, time.monotonic())
    delta = tick_delta * multiplier
    pending = state.encoder_pending_delta.get(channel_index, 0) + delta

    # Ohne diese Begrenzung laeuft der noch nicht committete Vorschauwert
    # (encoder_preview()) beliebig weiter, waehrend step_gain/step_pedestal
    # erst beim Commit (Encoder-Push) auf den Spec-Bereich clampen -- dann
    # kann die Anzeige z.B. "+239dB" zeigen, obwohl nur -6..+12dB bestaetigt
    # sind (AW-UE160_InterfaceSpecification_E.pdf Kap.9 "GAIN"/"OSL:25").
    value_range = _ENCODER_RANGES.get(function_name)
    field_name = _ENCODER_STATE_FIELDS.get(function_name)
    if value_range is not None and field_name is not None:
        cam_state = state.state_store.get_camera(entry.camera_id)
        confirmed = getattr(cam_state, field_name, None)
        if confirmed is not None:
            proposed = confirmed + pending
            clamped = max(value_range[0], min(value_range[1], proposed))
            pending = clamped - confirmed

    state.encoder_pending_delta[channel_index] = pending


async def commit_encoder_value(state: AppState, channel_index: int) -> None:
    """Encoder-Push (Note 32-39, Spec §9 "Verwendung des Encoder-Push...
    noch offen" -- jetzt per Nutzerentscheid belegt): sendet den seit der
    letzten Funktionsauswahl aufgelaufenen Pending-Wert als eine einzelne
    Kamera-Aenderung (`step_gain`/`step_pedestal` fragen den Ist-Wert dabei
    erneut ab und wenden das Gesamt-Delta darauf an, kein zusaetzlicher
    Zustand fuer den "Baseline"-Wert noetig). Kein Effekt ohne
    Kamera/Verbindung/vom Treiber unterstuetzte Funktion oder wenn seit der
    Funktionsauswahl nicht gedreht wurde (Delta 0)."""
    entry = state.mapping.get_channel("fader", channel_index)
    if entry is None:
        return
    functions = state.config.channel_defaults.encoder.functions
    if not functions:
        return
    function_name = functions[state.encoder_function_index.get(channel_index, 0) % len(functions)]
    method_name = _ENCODER_STEP_METHODS.get(function_name)
    field_name = _ENCODER_STATE_FIELDS.get(function_name)
    if method_name is None or field_name is None:
        return
    delta = state.encoder_pending_delta.get(channel_index, 0)
    if delta == 0:
        return
    camera_id = entry.camera_id
    driver = state.drivers.get(camera_id)
    if driver is None or not driver.connected:
        return
    step_method = getattr(driver, method_name, None)
    if step_method is None:
        return

    cam_state = state.state_store.get_camera(camera_id)
    try:
        new_value = await step_method(delta)
    except CameraCommandError as exc:
        cam_state.error = str(exc)
        await state.event_bus.publish("error", {"camera_id": camera_id, "message": str(exc)})
        return
    setattr(cam_state, field_name, new_value)
    cam_state.error = None
    state.encoder_pending_delta[channel_index] = 0
    await state.event_bus.publish("feature_changed", {"camera_id": camera_id, "key": f"encoder:{function_name}"})


def encoder_preview(state: AppState, channel_index: int) -> tuple[str, int] | None:
    """Aktive Encoder-Funktion + Vorschauwert (letzter bestaetigter
    Kamerawert + noch nicht committeter Pending-Delta) fuer Scribble-Strip
    (midi/fader.py) und Web-UI (`_channel_encoder_snapshot`). `None`, wenn
    die aktive Funktion ein reiner Anzeige-Eintrag ohne State-Feld ist
    (z. B. `camera_status`, Spec-Nutzerentscheid: dann zeigt das Display
    stattdessen Kamera-Name+Blende, der bisherige Default) oder der Ist-Wert
    (noch) nicht bekannt ist."""
    functions = state.config.channel_defaults.encoder.functions
    if not functions:
        return None
    function_name = functions[state.encoder_function_index.get(channel_index, 0) % len(functions)]
    field_name = _ENCODER_STATE_FIELDS.get(function_name)
    if field_name is None:
        return None
    entry = state.mapping.get_channel("fader", channel_index)
    if entry is None:
        return None
    cam_state = state.state_store.get_camera(entry.camera_id)
    confirmed = getattr(cam_state, field_name, None)
    if confirmed is None:
        return None
    return function_name, confirmed + state.encoder_pending_delta.get(channel_index, 0)


def _channel_encoder_snapshot(state: AppState, index: int) -> dict | None:
    """Encoder-Zustand fuer die Web-UI (Spec §9, Nutzerentscheid: Drehregler
    soll auch im Browser bedienbar sein, siehe web/app.py "encoder_turn"/
    "encoder_commit"). `None`, wenn keine Encoder-Funktionen konfiguriert
    sind (`channel_defaults.encoder.functions` leer). Bei `camera_status`
    (reiner Anzeige-Eintrag, siehe `cycle_encoder_function()`) ist `value`
    `None` -- die Web-UI zeigt Name+Blende ohnehin bereits im separaten
    Scribble-Strip-Panel (Nutzerentscheid: 2 Displays in der Web-UI bleiben,
    nur das reale Panel hat eines und braucht `camera_status` als
    eigenen Cycle-Eintrag)."""
    functions = state.config.channel_defaults.encoder.functions
    if not functions:
        return None
    function_name = functions[state.encoder_function_index.get(index, 0) % len(functions)]
    preview = encoder_preview(state, index)
    if preview is not None:
        value = preview[1]
        pending = bool(state.encoder_pending_delta.get(index, 0))
    else:
        value = None
        pending = False
    value_range = _ENCODER_RANGES.get(function_name)
    return {
        "function": function_name,
        "value": value,
        "pending": pending,
        "min": value_range[0] if value_range else None,
        "max": value_range[1] if value_range else None,
    }


def available_button_features(state: AppState, camera_id: str) -> dict[str, str]:
    """Feature-Katalog für die Setup-Dropdowns (Spec §9a: `key -> Label`).
    Leer, wenn der Treiber (bzw. das erkannte Kameramodell) keinen Katalog
    anbietet -- entspricht Spec §9a "kein Plugin-Modul -> keine
    Button-Belegung verfügbar"."""
    driver = state.drivers.get(camera_id)
    if driver is None:
        return {}
    return dict(getattr(driver, "BUTTON_FEATURE_LABELS", {}))


async def assign_channel_button(
    state: AppState, channel_index: int, button_slot: str, feature_key: str | None
) -> None:
    """Speichert die Button-2/3-Zuordnung eines Kanals dauerhaft in
    `config.yaml` (Spec §9a, per Nutzerentscheid: persistent statt nur
    Laufzeit). `feature_key=None`/leer löscht die Zuordnung wieder."""
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
    await state.event_bus.publish("config_changed", {"channel_index": channel_index})


async def apply_button_action(state: AppState, channel_index: int, button_slot: str) -> None:
    """Löst die einem Kanal-Button zugewiesene Kamera-Feature-Aktion aus
    (Spec §9a). Kein Effekt ohne Kamera/Zuordnung/Verbindung -- entspricht
    dem physischen Verhalten (ein Button ohne Belegung tut nichts)."""
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
        elif feature["kind"] == "trigger":
            await driver.trigger_button_feature(feature_key)
        else:  # "cycle"
            target = (int(cam_state.feature_states.get(feature_key, 0)) + 1) % len(feature["cycle"])
            await driver.cycle_button_feature(feature_key, target)
            cam_state.feature_states[feature_key] = target
    except CameraCommandError as exc:
        cam_state.error = str(exc)
        await state.event_bus.publish("error", {"camera_id": camera_id, "message": str(exc)})
        return
    cam_state.error = None
    await state.event_bus.publish("feature_changed", {"camera_id": camera_id, "key": feature_key})


def channel_snapshot(state: AppState) -> list[dict]:
    """Ein Eintrag je Kanalzug (1-8), Spec §10.2 "Übersicht". Kanaele ohne
    zugewiesene Kamera (kein Eintrag in `banks[0].channels`) haben
    `camera_id: None` und sind in der UI nicht steuerbar."""
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
    """Button-2/3-Zuordnung + zuletzt getrackter Zustand für einen Kanal
    (Spec §9a). `state` bei Cycle-Features der aktuelle Cycle-Index, bei
    Toggles bool -- siehe Kommentar an `CameraState.feature_states`."""
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
