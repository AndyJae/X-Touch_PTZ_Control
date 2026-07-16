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

import logging
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


async def connect_camera(state: AppState, camera_id: str) -> None:
    """Spec §11 Schritt 4 (ohne Notification-Registrierung/#LPC1, die in
    diesem Schritt noch nicht implementiert sind): `connect()` -> `QID` ->
    `get_state()` (Vollabzug)."""
    driver = state.drivers[camera_id]
    cam_state = state.state_store.get_camera(camera_id)
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
