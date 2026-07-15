"""core/application.py -- Anwendungsschicht (Spec §3 Core-Bausteine).

Verdrahtet Config/Treiber/Mapping-Engine/Rate-Limiter/EventBus zu einem
laufenden Prozess-Zustand (`AppState`) und stellt die Use-Cases bereit, die
ein Interface (Web-UI heute, X-Touch/MIDI später) aufruft: `connect_camera`,
`apply_iris`, `channel_snapshot`, `camera_status_list`. Kennt FastAPI nur an
der schmalen Stelle, an der tatsächlich WebSocket-Clients benachrichtigt
werden (`AppState.broadcast`) -- Routing/Templates gehören nicht hierher,
siehe `web/app.py`. Eine weitere Abstraktionsschicht für den einen
Broadcast-Mechanismus, den es gibt, wäre an dieser Stelle spekulativ.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from fastapi import WebSocket

from core.bus import EventBus
from core.config import AppConfig, CameraConfig
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
    ws_clients: set[WebSocket] = field(default_factory=set)

    async def broadcast(self, payload: dict) -> None:
        stale: list[WebSocket] = []
        for ws in self.ws_clients:
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.ws_clients.discard(ws)


def build_app_state(config: AppConfig) -> AppState:
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
    )
    _subscribe_snapshot_broadcast(state)
    return state


def _subscribe_snapshot_broadcast(state: AppState) -> None:
    """Web-UI ist nur ein Consumer des EventBus, kein Sonderfall: reagiert auf
    Kamera-Domain-Events (`iris_changed`, `connection_changed`, `error`) mit
    einem vollen State-Broadcast an alle WS-Clients. Ein späterer
    MIDI-Consumer (Motorfader-/LED-Feedback, Spec §5.4) würde dieselben
    Topics abonnieren, ohne dass dieser Code angefasst werden müsste."""

    async def _on_camera_event(_payload: dict) -> None:
        await state.broadcast({"type": "snapshot", "channels": channel_snapshot(state)})

    for topic in ("iris_changed", "connection_changed", "error"):
        state.event_bus.subscribe(topic, _on_camera_event)


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
                "connected": driver.connected if driver else False,
                "iris": cam_state.iris if cam_state else None,
                "gain_db": cam_state.gain_db if cam_state else None,
                "auto_iris": cam_state.auto_iris if cam_state else None,
                "error": cam_state.error if cam_state else None,
            }
        )
    return channels


def camera_status_list(state: AppState) -> list[dict]:
    """Spec §10.1 "Setup": Verbindungsstatus je Kamera."""
    result = []
    for camera_id, camera_cfg in state.cameras.items():
        driver = state.drivers[camera_id]
        cam_state = state.state_store.get_camera(camera_id)
        result.append(
            {
                "id": camera_id,
                "name": camera_cfg.name,
                "host": camera_cfg.host,
                "connected": driver.connected,
                "model": driver.model,
                "error": cam_state.error,
            }
        )
    return result
