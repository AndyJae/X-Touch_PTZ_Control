from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.bus import EventBus
from core.mapping import MappingEngine, build_mapping_from_config
from core.ratelimit import RateLimiter
from core.state import StateStore
from drivers.base import CameraCommandError, CameraDriver
from drivers.panasonic_aw import PanasonicAWDriver

LOGGER = logging.getLogger("ptz_control.web")

# Iris-Hysterese: 1 Digit der Geraete-Zielrange (555h-FFFh -> 2730 Schritte),
# Spec §8 "Nur bei Wertaenderung senden (Delta-Filter, Hysterese 1 Digit der
# Zielrange)".
_IRIS_HYSTERESIS = 1.0 / (0xFFF - 0x555)


def load_config(path: str | Path = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def build_driver(camera: dict) -> CameraDriver:
    driver_name = camera.get("driver", "panasonic_aw")
    if driver_name != "panasonic_aw":
        raise ValueError(f"unsupported driver: {driver_name!r} (v1: nur panasonic_aw)")
    return PanasonicAWDriver(host=camera["host"], port=camera.get("port", 80))


@dataclass
class AppState:
    """Pro-Prozess-Zustand, an `app.state.ptz` gehaengt (Spec §3 Core-Bausteine)."""

    config: dict
    event_bus: EventBus
    state_store: StateStore
    mapping: MappingEngine
    cameras: dict[str, dict]  # camera_id -> Config-Eintrag (id, name, host, port, ...)
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


def build_app_state(config: dict) -> AppState:
    cameras = {cam["id"]: cam for cam in config.get("cameras", [])}
    drivers: dict[str, CameraDriver] = {cid: build_driver(cam) for cid, cam in cameras.items()}
    rate_hz = float((config.get("global") or {}).get("rate_limit_hz", 15))
    rate_limiters = {cid: RateLimiter(rate_hz, hysteresis=_IRIS_HYSTERESIS) for cid in cameras}
    return AppState(
        config=config,
        event_bus=EventBus(),
        state_store=StateStore(),
        mapping=build_mapping_from_config(config),
        cameras=cameras,
        drivers=drivers,
        rate_limiters=rate_limiters,
    )


async def connect_camera(state: AppState, camera_id: str) -> None:
    """Spec §11 Schritt 4 (ohne Notification-Registrierung/#LPC1, die in
    diesem Schritt noch nicht implementiert sind): `connect()` -> `QID` ->
    `get_state()` (Vollabzug)."""
    driver = state.drivers[camera_id]
    cam_state = state.state_store.get_camera(camera_id)
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config = load_config()
    state = build_app_state(config)
    app.state.ptz = state
    # Spec §11: Web-UI startet immer, auch wenn Kameras fehlen/nicht erreichbar
    # sind -- Fehler werden pro Kamera geloggt, der Prozess bricht nicht ab.
    for camera_id in state.drivers:
        try:
            await connect_camera(state, camera_id)
        except Exception as exc:  # defensiv: Startup darf nie an einer Kamera scheitern
            LOGGER.warning("Kamera %s: Connect fehlgeschlagen: %s", camera_id, exc)
            state.state_store.get_camera(camera_id).error = str(exc)
    LOGGER.info("PTZ Control Web-UI bereit: %d Kamera(s) konfiguriert", len(state.drivers))
    yield
    for driver in state.drivers.values():
        await driver.disconnect()


app = FastAPI(title="PTZ Control", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="web/static"), name="static")

templates = Jinja2Templates(directory="web/templates")


def _ptz_state(request: Request) -> AppState:
    return request.app.state.ptz


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
                "name": camera_cfg.get("name", camera_id) if camera_cfg else None,
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
                "name": camera_cfg.get("name", camera_id),
                "host": camera_cfg.get("host"),
                "connected": driver.connected,
                "model": driver.model,
                "error": cam_state.error,
            }
        )
    return result


@app.get("/", response_class=HTMLResponse)
async def surface_page(request: Request) -> HTMLResponse:
    state = _ptz_state(request)
    return templates.TemplateResponse(
        request=request,
        name="surface.html",
        context={"active_page": "surface", "channels": channel_snapshot(state)},
    )


@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request) -> HTMLResponse:
    state = _ptz_state(request)
    return templates.TemplateResponse(
        request=request,
        name="setup.html",
        context={"active_page": "setup", "cameras": camera_status_list(state)},
    )


@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="config.html", context={"active_page": "config"})


@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="logs.html", context={"active_page": "logs"})


@app.post("/api/cameras/{camera_id}/connect")
async def api_connect_camera(camera_id: str, request: Request) -> JSONResponse:
    state = _ptz_state(request)
    if camera_id not in state.drivers:
        return JSONResponse({"connected": False, "error": "unbekannte Kamera-ID"}, status_code=404)
    try:
        await connect_camera(state, camera_id)
    except Exception as exc:
        return JSONResponse({"connected": False, "error": str(exc)}, status_code=502)
    driver = state.drivers[camera_id]
    cam_state = state.state_store.get_camera(camera_id)
    payload = {"connected": driver.connected, "model": driver.model, "error": cam_state.error}
    await state.broadcast({"type": "snapshot", "channels": channel_snapshot(state)})
    return JSONResponse(payload)


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
    else:
        cam_state.iris = value
        cam_state.error = None
    state.event_bus.publish(
        "channel.value_changed",
        {"channel_index": channel_index, "camera_id": camera_id, "value": value},
    )
    await state.broadcast({"type": "snapshot", "channels": channel_snapshot(state)})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    state: AppState = websocket.app.state.ptz
    state.ws_clients.add(websocket)
    try:
        await websocket.send_json({"type": "snapshot", "channels": channel_snapshot(state)})
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "set_iris":
                channel_index = int(message["channel"])
                value = float(message["value"])
                final = bool(message.get("final", False))
                await apply_iris(state, channel_index, value, final=final)
    except WebSocketDisconnect:
        pass
    finally:
        state.ws_clients.discard(websocket)
