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
    # Delta, das ein Dreh-Tick zwar auf die aktive Funktion anwenden will,
    # aber der Rate-Limiter unten noch zurueckhaelt -- wird beim naechsten
    # erlaubten Tick nachgereicht (siehe `apply_encoder_turn`), damit bei
    # schnellem Drehen kein Teil-Delta stillschweigend verloren geht.
    encoder_pending_delta: dict[int, int] = field(default_factory=dict)
    # Visuelles "gespeichert"-Flag je Kanal (Encoder-Push, Nutzerentscheid):
    # rot in der Web-UI, bis der naechste Dreh-Tick es wieder zuruecksetzt
    # (siehe `apply_encoder_turn`/`commit_encoder_value`).
    encoder_saved: dict[int, bool] = field(default_factory=dict)
    # Encoder-Drehung sendet Gain/Pedestal seit Nutzerentscheid live pro Tick
    # (statt Preview/Commit) -- eigene Rate-Limiter-Instanz pro Kamera, damit
    # nicht jeder MIDI-Tick einen eigenen HTTP-Request ausloest (analog zu
    # `rate_limiters` fuer den Iris-Fader, aber getrennt: anderer
    # Wertebereich, keine Hysterese noetig, siehe `build_app_state`).
    encoder_rate_limiters: dict[str, RateLimiter] = field(default_factory=dict)
    # Ob die zuletzt gespeicherte Companion-Config tatsaechlich erreichbar
    # war (echte Pruefung per is_reachable, siehe configure_companion und
    # web/app.py lifespan) -- unabhaengig davon, ob ueberhaupt ein Host in
    # der Config steht (Bugfix: `companion.host` truthy != Companion laeuft
    # gerade). Startet konservativ bei False, bis eine echte Pruefung das
    # Gegenteil belegt.
    companion_connected: bool = False

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
    """Web-UI ist nur ein Consumer des EventBus, kein Sonderfall: reagiert auf
    Kamera-Domain-Events (`iris_changed`, `connection_changed`, `error`,
    `feature_changed`, `config_changed`, `gain_changed`, `pedestal_changed`,
    `nd_changed`) mit einem vollen State-Broadcast an alle WS-Clients. Ein
    späterer MIDI-Consumer (Motorfader-/LED-Feedback, Spec §5.4) würde
    dieselben Topics abonnieren, ohne dass dieser Code angefasst werden
    müsste."""

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
    """Fragt die F-Nummer separat nach (`driver.query_f_number()`, nur dieses
    eine Feld statt des vollen `get_state()`) und publiziert erneut
    `iris_changed`, damit Web-UI-Snapshot und Scribble-Strip (beide bereits
    auf dieses Topic abonniert) die aufgefrischte F-Nummer mitnehmen --
    siehe Aufrufstelle in `_wire_camera_events()`."""
    cam_state = state.state_store.get_camera(camera_id)
    cam_state.iris_f_number = await driver.query_f_number()
    await state.event_bus.publish("iris_changed", {"camera_id": camera_id, "value": cam_state.iris})


def _wire_camera_events(state: AppState, camera_id: str, driver: CameraDriver) -> None:
    """Bruecke Treiber-Events (`subscribe()`, sync per ABC §6) auf den
    EventBus (async) -- damit reagieren Web-UI und MIDI-Motorfader auch auf
    Aenderungen, die nicht von PTZ_Control selbst ausgeloest wurden (z. B.
    Kamera-eigenes Web-UI), siehe `drivers/panasonic_aw.py`s
    Lens-Info-Feedback (§7.3) sowie die generische Update-Notification-
    Auswertung (§4.2 der HD Integrated Camera Interface Specifications) in
    `_handle_notification()` fuer Toggle-Features/Gain/Pedestal/ND-Filter."""

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
                # Bugreport 2026-07-23 (live gegen die reale AW-UE160,
                # externe Auto-Iris-Bewegung): das lPI-Lens-Info-Frame (§7.3.2)
                # traegt nur die rohe Iris-POSITION, keine F-Nummer -- ohne
                # diesen Zweig blieb `iris_f_number` bei jeder extern (nicht
                # ueber apply_iris()) ausgeloesten Positionsaenderung auf dem
                # zuletzt bekannten Stand stehen (live bestaetigt: App zeigte
                # "F11.0", Kamera-QIF/-OSD zeigten "F6.4"). Nur bei
                # tatsaechlicher Positionsaenderung (nicht bei jedem
                # ~300ms-Notification-Heartbeat) neu abfragen, analog zur
                # Drosselung in apply_iris() ueber den Rate-Limiter.
                asyncio.create_task(_refresh_f_number_from_notification(state, camera_id, driver))
        elif event_type == "feature_changed":
            state.state_store.get_camera(camera_id).feature_states[event["key"]] = event["enabled"]
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
    verbundenen Zustand erneut geklickt -> Entkoppeln) UND entfernt die
    Registrierung komplett aus `config.yaml` (Nutzerentscheid 2026-07-20,
    Bugreport: `config.yaml` sammelte sonst dauerhaft jede je verbundene
    Kamera an, auch nach dem Trennen -- ein erneutes "Connect Camera"
    braucht danach wieder Name/IP/Port).

    Setzt zuerst `iris` auf 0.0 zurueck und published `connection_changed`
    (Bugreport 2026-07-20: Motorfader blieb sonst auf der zuletzt bekannten
    Position stehen) -- `midi/fader.py::_on_connection_changed()` fährt den
    physischen Motorfader daraufhin auf 0, WAEHREND die Kanal-Zuordnung noch
    existiert (sonst fände `_channel_for_camera()` den Kanal nicht mehr).
    Erst DANACH werden Kamera-Config, Bank-Kanal-Zuordnung und Mapping
    entfernt und `config_changed` published, damit Scribble-Strips/Web-UI
    den Kanal als komplett unbelegt (kein Name, "----") zeigen, nicht nur
    als "NC" (zugewiesen, aber getrennt)."""
    driver = state.drivers.get(camera_id)
    if driver is None:
        return
    await driver.disconnect()
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


async def register_camera(
    state: AppState, channel_index: int, *, name: str, host: str, port: int
) -> None:
    """Registriert/aktualisiert eine Kamera für einen Kanal über die
    Setup-Tabelle ("Connect Camera"-Button). Bewusste Abkehr von der
    ursprünglichen Spec-§10.3-Entscheidung "kein Formular-Editor" für
    Kamera-Stammdaten (Nutzerentscheid) -- die freie YAML-Ansicht aus §10.3
    ist davon nicht betroffen. Kamera-ID ist deterministisch `cam{channel}`,
    da die Tabelle kein eigenes ID-Feld hat; erneuter Aufruf für denselben
    Kanal aktualisiert damit dieselbe Kamera statt eine zweite anzulegen.

    Lehnt eine IP ab, die bereits einem ANDEREN Kanal zugeordnet ist
    (Bugreport 2026-07-20: zwei Kanäle auf derselben physischen Kamera
    teilen sich unbemerkt Zustand wie Lens-Info-Push, Gain, Pedestal --
    siehe CLAUDE.md Offene Punkte) -- derselbe Host für denselben Kanal
    (erneutes Connect/Update) bleibt erlaubt."""
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


async def configure_companion(state: AppState, host: str, port: int, connected: bool = False) -> None:
    """Speichert die globale Bitfocus-Companion-Instanz (eine für alle
    Kanäle, Nutzerentscheid) -- Setup-Seite, Panel an der Stelle des
    ehemaligen "Camera Status"-Blocks. `connected` kommt vom Aufrufer, der
    die tatsaechliche Erreichbarkeit (is_reachable) bereits geprueft hat --
    hier bewusst kein eigener Check, um den Request nicht zu duplizieren."""
    state.config.companion.host = host.strip()
    state.config.companion.port = port
    state.companion_connected = connected
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
    """Datenfluss Fader -> Kamera, Spec §3: Mapping -> Rate-Limiter -> Driver.

    Fragt nach jedem tatsaechlich gesendeten Tick (d. h. jedem Tick, den der
    Rate-Limiter durchlaesst, nicht nur bei `final=True`) zusaetzlich die
    F-Nummer-Anzeige neu ab (`driver.query_f_number()`) -- Nutzerentscheid
    2026-07-23, revidiert (erste Fassung fragte nur bei `final=True`):
    anders als die lokal berechenbare Iris-%, gibt es fuer die F-Nummer keine
    Formel aus der Fader-Position, nur die Kamera-eigene QIF-Abfrage. Eine
    einzelne QIF-Abfrage ist klein genug, um pro Tick keinen spuerbaren
    Zusatz-Traffic zu verursachen -- `query_f_number()` fragt bewusst nur
    dieses eine Feld ab, nicht den vollen `get_state()` (Gain/Pedestal/ND/
    Fehler waeren hier unnoetig)."""
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
        cam_state.iris_f_number = await driver.query_f_number()
        await state.event_bus.publish("iris_changed", {"camera_id": camera_id, "value": value})


# --- Encoder-Funktionsauswahl + -Drehung (Spec §9) --------------------------
# Button 1 (physisch Rec) schaltet fest durch diese Liste (Nutzerentscheid:
# nicht mehr ueber `config.yaml` konfigurierbar, siehe core/config.py).
# `camera_status` steht bewusst an erster Stelle (Nutzerauftrag 2026-07-23):
# ohne jeden Button-1-Druck (App-Start, Kamera-Connect) zeigt Button 1 damit
# zuerst "Camera Info" statt "Gain" -- alle Default-Index-Lookups fallen auf
# `.get(channel_index, 0)` zurueck (siehe channel_display_text() u. a.).
# Shutter ist per Nutzerentscheid komplett aus dem Scope entfernt (kein
# Treiber-Code, keine Config, kein Encoder-Eintrag), nicht nur zurueckgestellt.
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
_ENCODER_ACCEL_WINDOW = 0.1  # Spec §9: "Klicks/100 ms > 3 -> Beschleunigung x5"
_ENCODER_ACCEL_THRESHOLD = 3
_ENCODER_ACCEL_MULTIPLIER = 5


def _encoder_multiplier(state: AppState, channel_index: int, now: float) -> int:
    history = state.encoder_tick_history.setdefault(channel_index, [])
    history[:] = [t for t in history if now - t < _ENCODER_ACCEL_WINDOW]
    history.append(now)
    return _ENCODER_ACCEL_MULTIPLIER if len(history) > _ENCODER_ACCEL_THRESHOLD else 1


def _encoder_value_range(driver: CameraDriver | None, function_name: str) -> tuple[int, int] | None:
    """Wertebereich fuer `gain`/`pedestal` aus dem verbundenen Treiber --
    modellabhaengig (siehe drivers/panasonic_aw.py::_apply_model_catalog(),
    `drivers/panasonic_models/*.py`), ersetzt die fruehere statische
    `_ENCODER_RANGES`-Konstante, die fuer JEDES Modell AW-UE160-Werte
    (-6..+12dB/-200..+200) annahm. `None` heisst "kein Treiber" oder "Modell
    ohne bekannten Wertebereich" (z. B. unbekanntes Modell oder eines der
    Modelle ohne Gain-/Pedestal-Eintrag in den beiden Referenz-PDFs) -- kein
    erfundener Fallback. `gain`s Obergrenze ist `effective_gain_max_db`
    (Nutzerauftrag 2026-07-20) statt des statischen `gain_max_db` -- bei
    Modellen mit Super-Gain-Kopplung (aw_ue100.py/aw_ue80.py/aw_ue150.py/
    aw_he145.py) 36dB statt 42dB, solange Super Gain nicht als "an"
    bestaetigt ist (live gegen AW-UE100 verifiziert: Werte >36dB werden von
    der Kamera per ER3 abgelehnt)."""
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
    """Button 1 (physisch Rec, Spec §9 "Encoder-Funktionsauswahl"): schaltet
    nur lokal durch `_ENCODER_FUNCTIONS`, sendet selbst keinen Kamerabefehl.
    `camera_status` ist ein reiner Anzeige-Eintrag ohne Step-Methode/
    State-Feld -- Kamera-Name+Blende (Spec: "Camera Status") statt
    Funktion+Wert, siehe `encoder_preview()`/`channel_display_text()`.

    Fragt beim Wechsel zu einem echten Parameter sofort dessen Ist-Wert ab
    (Nutzerentscheid), damit die naechste Encoder-Drehung auf dem echten
    Kamerawert aufsetzt statt auf einem veralteten/lokalen Wert. Ein zweiter
    Button-1-Druck waehrend dieser Abfrage wartet implizit, da der
    MIDI-Rx-Poll-Loop Nachrichten sequenziell abarbeitet (siehe
    midi/fader.py `_poll_loop`).

    Setzt auch das "gespeichert"-Anzeigeflag (`encoder_saved`) und ein noch
    nicht an die Kamera nachgereichtes Pending-Delta der zuvor aktiven
    Funktion zurueck -- beides gehoert zur vorherigen Funktion, nicht zur
    neu ausgewaehlten."""
    new_index = (state.encoder_function_index.get(channel_index, -1) + 1) % len(_ENCODER_FUNCTIONS)
    state.encoder_function_index[channel_index] = new_index
    function_name = _ENCODER_FUNCTIONS[new_index]
    state.encoder_pending_delta[channel_index] = 0
    state.encoder_saved[channel_index] = False

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
    """Encoder-Drehung bei `gain`/`pedestal`/`nd`: sendet den neuen Wert seit
    Nutzerentscheid SOFORT live an die Kamera (ersetzt das fruehere
    Preview/Commit-Verhalten) -- ueber `state.encoder_rate_limiters`, damit
    nicht jeder einzelne MIDI-Tick einen eigenen HTTP-Request ausloest
    (dieselbe Idee wie `apply_iris`, aber eigene Limiter-Instanz je Kamera:
    anderer Wertebereich, keine Hysterese). Ein Tick, den der Limiter gerade
    zurueckhaelt, geht NICHT verloren, sondern sammelt sich in
    `encoder_pending_delta` und wird beim naechsten erlaubten Tick als
    Gesamt-Delta nachgereicht.

    `nd` (Nutzerauftrag 2026-07-22) ist eine geordnete, modellabhaengige und
    teils lueckenhafte Werteliste (`driver.nd_options`) statt eines
    kontinuierlichen Zahlenbereichs -- eigener Zweig weiter unten, der in
    LISTENPOSITIONEN statt Roh-Data-Werten rechnet und am Rand anschlaegt
    (kein Wrap).

    `tick_delta` ist ein bereits dekodiertes, vorzeichenbehaftetes Delta
    (ein "Klick") -- die MIDI-CC-Dekodierung (Spec §5.2/§9: Wert 1-7 = +,
    65-71 = -) lebt in `midi.mackie.MackieControlProtocol.encoder_cc_to_delta`,
    die Web-UI liefert das Delta direkt (siehe web/app.py WebSocket
    "encoder_turn"). Kein Effekt ohne Kamera/Verbindung/bekannten Ist-Wert
    oder bei `camera_status` (reiner Anzeige-Eintrag, kein Eintrag in
    `_ENCODER_STATE_FIELDS`).

    Der vorgeschlagene Wert wird auf denselben Bereich geclampt wie das
    UI-Display (`_encoder_value_range()`, modellabhaengig ueber den
    verbundenen Treiber) -- ohne dieses Clamping liefe der Wert beliebig
    weiter (frueherer Bug: Anzeige zeigte z. B. "+239dB", damals noch mit
    fest verdrahteten AW-UE160-Grenzen).

    Ein Tick bewegt bei `gain` um `driver.gain_step_db` statt immer um 1dB
    (Bugfix 2026-07-18, siehe CLAUDE.md-Offene-Punkte): die 3dB-Schritt-
    Modelle (AW-HE50/60/HE40/UE70/HE42) akzeptieren laut PDF nur 0/3/6/9dB
    usw. -- `GAIN_MIN_DB`/`GAIN_MAX_DB` sind bei diesen Modellen beide
    Vielfache von `GAIN_STEP_DB`, daher bleibt auch der geclampte Wert immer
    ein gueltiges Vielfaches. `pedestal` hat kein Schrittweiten-Feld, bleibt
    unveraendert bei 1 pro Klick.

    Jeder tatsaechliche Dreh-Tick setzt `encoder_saved` zurueck (Nutzerent-
    scheid: die "gespeichert"-Anzeige gilt nur bis zum naechsten Dreh)."""
    entry = state.mapping.get_channel("fader", channel_index)
    if entry is None:
        return
    function_name = _ENCODER_FUNCTIONS[state.encoder_function_index.get(channel_index, 0) % len(_ENCODER_FUNCTIONS)]
    field_name = _ENCODER_STATE_FIELDS.get(function_name)
    if field_name is None:
        return  # camera_status: reiner Anzeige-Eintrag, keine Kamera-Aktion
    camera_id = entry.camera_id
    driver = state.drivers.get(camera_id)
    if driver is None or not driver.connected:
        return

    state.encoder_saved[channel_index] = False

    now = time.monotonic()
    multiplier = _encoder_multiplier(state, channel_index, now)
    # Modelle mit `GAIN_STEP_DB` > 1 (z. B. AW-HE50/60/HE40/UE70/HE42: nur
    # 3dB-Schritte laut PDF) akzeptieren keine beliebigen Zwischenwerte -- ein
    # Tick muss deshalb um einen vollen Schritt bewegen, nicht immer um 1dB
    # (frueher offener Punkt, siehe CLAUDE.md: "Verhalten der Kamera bei
    # einem solchen Zwischenwert (z. B. OGU:09) ist nicht dokumentiert").
    # `pedestal` hat kein Schrittweiten-Feld, bleibt bei 1.
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
        # Aktuell in Gain-Auto/AGC (Data=0x80, Nutzerauftrag 2026-07-20,
        # live gegen AW-UE160 UND AW-UE100 bestaetigt): kein numerischer
        # Ist-Wert vorhanden, deshalb kein Rate-Limiter/Delta-Clamping wie
        # unten -- Hochdrehen (pending>0) verlaesst Auto, Runterdrehen bleibt
        # in Auto (kein tieferer Zustand). Der Ausstieg selbst verhaelt sich
        # dabei genauso proportional/beschleunigt wie jedes andere Drehen
        # (Nutzerentscheid 2026-07-20, revidiert -- kein Sonder-"Verschlucken"
        # der ganzen Drehbewegung mehr): `step_gain()` behandelt Auto intern
        # als virtuelle Position "eine Stufe unter gain_min_db" und landet
        # bei `gain_min_db + (pending-1)`, geclampt auf
        # `effective_gain_max_db`. Bewusst OHNE Rate-Limiter: der
        # Auto<->Manuell-Uebergang ist eine seltene Grenzueberschreitung,
        # kein kontinuierliches Ziehen wie bei Iris/normalem Gain-Drehen.
        if pending <= 0 or step_method is None:
            state.encoder_pending_delta[channel_index] = min(pending, 0)
            return
        try:
            new_db, new_auto = await step_method(pending)
        except CameraCommandError as exc:
            cam_state.error = str(exc)
            # Bugreport 2026-07-20: ein von der Kamera abgelehnter Wert
            # (z. B. ER3, siehe naechster Punkt) durfte das "pending"-Delta
            # nicht stehen lassen -- sonst zeigt die naechste Vorschau
            # (encoder_preview()) einen nie tatsaechlich erreichten Wert.
            state.encoder_pending_delta[channel_index] = 0
            await state.event_bus.publish("error", {"camera_id": camera_id, "message": str(exc)})
            return
        cam_state.gain_db = new_db
        cam_state.gain_auto = new_auto
        cam_state.error = None
        state.encoder_pending_delta[channel_index] = 0
        return

    if function_name == "nd":
        # ND ist eine geordnete, teils lueckenhafte Werteliste (z. B.
        # AW-HE130/AW-HR140: nur Data 0/3/4, siehe drivers/panasonic_models/
        # aw_he130.py) -- anders als gain/pedestal keine kontinuierliche
        # Zahlenreihe, `pending`/`confirmed` sind deshalb hier LISTEN-
        # POSITIONEN, nicht Roh-Data-Werte. Anschlag am Rand (kein Wrap,
        # Nutzerentscheid 2026-07-22) -- anders als `PanasonicAWDriver.
        # cycle_nd()`, das fuer den (noch nicht verdrahteten) Mute-Button-
        # Anwendungsfall weiterhin rundenweise durchschaltet.
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
        # Gain-Unterschreitung des Minimums NICHT auf das Minimum clampen
        # (Nutzerauftrag 2026-07-20) -- ein weiteres Herunterdrehen unter
        # `gain_min_db` soll stattdessen in Auto wechseln (siehe
        # PanasonicAWDriver.step_gain()); der obere Rand bleibt geclampt.
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
        # Bugreport 2026-07-20 (live gegen AW-UE100 mit Super Gain aus:
        # Werte >36dB werden von der Kamera mit ER3 abgelehnt, siehe
        # drivers/panasonic_models/aw_ue100.py) -- ein abgelehnter Wert darf
        # das "pending"-Delta nicht stehen lassen, sonst zeigt die naechste
        # Vorschau (encoder_preview()) einen nie tatsaechlich erreichten Wert
        # (das war die Ursache der faelschlich "+42" angezeigten Vorschau).
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
    # Bewusst KEIN "feature_changed"-Event hier (anders als commit_encoder_value
    # unten): das wuerde bei jedem einzelnen Dreh-Tick einen vollen
    # 8-Strip-Scribble-Refresh in midi/fader.py ausloesen (siehe dessen
    # Modul-Docstring "Tx Scribble Strips"). Aufrufer aktualisieren die
    # Anzeige stattdessen gezielt selbst (midi/fader.py::_refresh_channel_line2,
    # web/app.py WebSocket-Handler "encoder_turn").


async def commit_encoder_value(state: AppState, channel_index: int) -> None:
    """Encoder-Push (Note 32-39, Spec §9 "Verwendung des Encoder-Push...
    noch offen" -- jetzt per Nutzerentscheid belegt): seit der Umstellung auf
    Live-Senden (siehe `apply_encoder_turn`) rein visuelles Feedback -- der
    Kamerawert ist zu diesem Zeitpunkt bereits aktuell, es wird also KEIN
    zusaetzlicher Kamerabefehl gesendet. Markiert den Kanal nur als
    "gespeichert" (`encoder_saved`, rote Anzeige in der Web-UI bis zum
    naechsten Dreh-Tick). Kein Effekt bei `camera_status` (kein Wert zum
    Speichern) oder ohne zugewiesene Kamera."""
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
    """Aktive Encoder-Funktion + aktueller Wert (letzter bestaetigter
    Kamerawert + ein evtl. noch vom Rate-Limiter zurueckgehaltenes Delta,
    siehe `apply_encoder_turn`) fuer Scribble-Strip (midi/fader.py) und
    Web-UI (`channel_display_text`/`_channel_encoder_snapshot`). `None`,
    wenn die aktive Funktion ein reiner Anzeige-Eintrag ohne State-Feld ist
    (z. B. `camera_status`, Spec-Nutzerentscheid: dann zeigt das Display
    stattdessen Kamera-Name+Blende) oder der Ist-Wert (noch) nicht bekannt
    ist. Der Wert selbst ist `None`, wenn `gain` gerade in Auto/AGC ist
    (Nutzerauftrag 2026-07-20) -- anders als eine komplett unbekannte
    Funktion liefert diese Funktion dann trotzdem ein Tupel (Zeile 1 zeigt
    weiterhin "GAIN"), `_encoder_value_text()`/`_channel_encoder_snapshot()`
    behandeln den `None`-Wert als "AUTO". Bei `nd` ist der zurueckgegebene
    Wert der Roh-Data-Wert der Zielposition (nicht die Listenposition
    selbst) -- `encoder_pending_delta` ist fuer `nd` in LISTENPOSITIONEN
    gezaehlt (siehe `apply_encoder_turn`), muss hier also erst auf eine
    Position abgebildet werden, bevor der zugehoerige Roh-Wert aufgeloest
    wird."""
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
    """Aktive Funktion, wenn sie `gain`/`pedestal`/`nd` ist UND das
    verbundene Kameramodell dafuer laut den lokalen Referenz-PDFs gar keine
    Daten hat (`_encoder_value_range()` liefert dann `None` fuer `gain`/
    `pedestal`, `driver.nd_options` ist leer/`None` fuer `nd` -- z. B.
    AW-HE40/AW-HE50/AW-HE60 haben gar keinen physischen ND-Filter, siehe
    drivers/panasonic_models/aw_he40.py/aw_he50.py) -- sonst `None`.
    Unterscheidet dieses "vom Modell nicht unterstuetzt" (Bugreport
    2026-07-18: Button 1 wechselte sichtbar auf GAIN/PEDESTAL, aber die
    Wertanzeige blieb stumm beim Camera-Status-Inhalt haengen) von "Wert nur
    gerade nicht bekannt" (z. B. Kamera nicht verbunden, AGC aktiv) --
    letzteres faellt weiterhin auf die bisherige Iris-%/Kameraname-Anzeige
    zurueck, siehe `channel_display_text`/`channel_line1_text`."""
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
    """Label des ND-Filter-Data-Werts `index` laut `driver.nd_options`
    (z. B. "1/64") -- `None`, wenn `index` unbekannt ist oder der Treiber
    keinen ND-Katalog hat. Alle bisher portierten Labels passen in das
    7-Zeichen-Limit des Scribble-Strips (siehe `_encoder_value_text`)."""
    if index is None:
        return None
    nd_options = getattr(driver, "nd_options", None) or []
    for opt_index, label in nd_options:
        if opt_index == index:
            return label
    return None


def _encoder_value_text(function_name: str, value: int | None) -> str:
    """Kompakte Darstellung des aktiven Encoder-Werts (7-Zeichen-Limit des
    Scribble-Strips, Spec §5.3 -- kein LED-Ring verfuegbar, siehe
    midi/fader.py-Modul-Docstring). Kein Funktions-Praefix (G/P) mehr --
    Zeile 1 zeigt seit Nutzerentscheid bereits den Funktionsnamen
    (`channel_line1_text`), ein zusaetzliches Praefix in Zeile 2 waere
    redundant. `gain` ist der einzige mit physikalischer Einheit (dB);
    `pedestal` ist bei der AW-UE160 ein unitloser Rohwert -200..+200
    (`AW-UE160_InterfaceSpecification_E.pdf` Kap. 9 `OSJ:0F`), keine
    Prozentangabe. `value` ist `None`, wenn `gain` in Auto/AGC ist
    (Nutzerauftrag 2026-07-20, siehe `encoder_preview()`) -- zeigt dann
    "AUTO" statt eines dB-Werts."""
    if value is None:
        return "AUTO"
    suffix = "dB" if function_name == "gain" else ""
    return f"{value:+d}{suffix}"


def channel_display_text(state: AppState, channel_index: int) -> str:
    """Zeile 2 der EINEN Kanal-Anzeige -- Nutzerentscheid: physisches
    Scribble-Strip (`midi/fader.py`) und Web-UI zeigen exakt denselben Wert
    ueber dieselbe Funktion, kein eigenes Web-UI-Format mehr. Bei
    `camera_status` die Iris-F-Nummer (`cam_state.iris_f_number`, z. B.
    "F9.8"/"CLOSE" -- Nutzerauftrag 2026-07-23: F-Nummer statt Iris-% als
    Anzeige, live gegen eine reale AW-UE160 kalibriert, siehe
    drivers/panasonic_aw.py::_decode_f_number()), bei `gain`/`pedestal` der
    jeweilige Funktionswert (siehe `encoder_preview`), bei `nd` das Label des
    Ziel-Data-Werts (z. B. "1/64", siehe `_nd_label`) -- oder "n/a", wenn
    das Modell diese Funktion gar nicht unterstuetzt
    (`_encoder_function_unsupported()`, Nutzerentscheid 2026-07-18: explizit
    statt stillschweigend auf eine Platzhalter-Anzeige zurueckzufallen) oder
    die F-Nummer (noch) nicht bekannt ist."""
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
    """Zeile 1 der EINEN Kanal-Anzeige -- Nutzerentscheid: bei `camera_status`
    der Kameraname (bisheriges Verhalten), bei `gain`/`pedestal` stattdessen
    der Funktionsname (GAIN/PEDESTAL), damit sofort erkennbar ist, worauf
    sich der Wert in Zeile 2 (`channel_display_text`) bezieht -- ohne das
    waere z. B. "+45" ohne Kontext mehrdeutig (Gain in dB? Pedestal-Digit?).
    Zeigt den Funktionsnamen auch dann, wenn das Modell die Funktion gar
    nicht unterstuetzt (`_encoder_function_unsupported()`) -- sonst waere
    Zeile 2 "n/a" ohne erkennbaren Bezug."""
    preview = encoder_preview(state, channel_index)
    if preview is None:
        unsupported = _encoder_function_unsupported(state, channel_index)
        if unsupported is not None:
            return unsupported.upper()
        return camera_name or ""
    function_name, _ = preview
    return function_name.upper()


def _channel_encoder_snapshot(state: AppState, index: int) -> dict:
    """Encoder-Zustand fuer die Web-UI (Spec §9, Nutzerentscheid: Drehregler
    soll auch im Browser bedienbar sein, siehe web/app.py "encoder_turn"/
    "encoder_commit"). Bei `camera_status` (reiner Anzeige-Eintrag, siehe
    `cycle_encoder_function()`) ist `value` `None` -- die Web-UI zeigt
    Name+Blende dann ueber `channel_display_text` (dieselbe EINE Anzeige wie
    das physische Scribble-Strip, kein separates zweites Display mehr,
    Nutzerentscheid). `saved` steuert das rote "gespeichert"-Feedback nach
    einem Encoder-Push (`commit_encoder_value`), bis zum naechsten Dreh-Tick."""
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
    Laufzeit). `feature_key=None`/leer löscht die Zuordnung wieder.

    Fragt bei Zuweisung eines Toggle-Features mit bekanntem Query-Kommando
    (Nutzerentscheid 2026-07-18, siehe `PanasonicAWDriver.
    query_button_feature()`) sofort den Ist-Zustand ab, damit der Button in
    der Web-UI korrekt beleuchtet/unbeleuchtet erscheint statt erst nach dem
    ersten Druck einen (dann nur lokal geratenen) Zustand zu haben. Ohne
    bekanntes Query-Kommando (siehe `query_button_feature()`-Docstring) oder
    ohne verbundene Kamera bleibt der Zustand wie bisher unbekannt, bis zum
    ersten Druck."""
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
    """Löst die einem Kanal-Button zugewiesene Kamera-Feature-Aktion aus
    (Spec §9a). Kein Effekt ohne Kamera/Zuordnung/Verbindung -- entspricht
    dem physischen Verhalten (ein Button ohne Belegung tut nichts).

    Nur noch "toggle"/"trigger" (Nutzerentscheid 2026-07-18): mehrwertige
    Kamera-Parameter (Knee, DRS) sind kein eigener "cycle"-Feature-Typ mehr,
    sondern je ein Toggle pro Zielzustand (z. B. "knee_auto"), siehe
    drivers/panasonic_aw.py-Klassendocstring -- Button 2/3 haben eine
    einzelne, nicht mehrfarbige LED und koennen so nur echt an/aus
    darstellen, kein rundenweises Durchschalten. Das Cycle-Konzept lebt
    weiterhin bei Button 1 (Encoder-Funktionsauswahl, siehe
    `cycle_encoder_function()`), das ist ein komplett getrennter
    Mechanismus ohne Bezug zu BUTTON_FEATURES."""
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
        else:  # "trigger"
            await driver.trigger_button_feature(feature_key)
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
                # EINE Kanal-Anzeige fuer Web-UI und physisches Scribble-Strip
                # (Nutzerentscheid): Zeile 1 Kameraname/Funktionsname, Zeile 2
                # Iris-F-Nummer/Funktionswert -- siehe channel_line1_text()/
                # channel_display_text().
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
    """Button-2/3-Zuordnung + zuletzt getrackter Zustand für einen Kanal
    (Spec §9a). `state` ist bool (an/aus), siehe Kommentar an
    `CameraState.feature_states`."""
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
