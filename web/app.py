"""web/app.py -- Interface-Schicht: FastAPI-Routen, WebSocket, Templates.

Enthält bewusst keine Domain-/Anwendungslogik (Treiber-Verdrahtung,
Mapping->Rate-Limiter->Driver-Fluss, State-Aufbereitung) -- die lebt in
`core/application.py` und ist von hier unabhängig testbar. Dieses Modul
übersetzt nur zwischen HTTP/WebSocket und den dortigen Use-Cases.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.application import (
    AppState,
    apply_iris,
    build_app_state,
    camera_status_list,
    channel_snapshot,
    connect_camera,
)
from core.config import load_config

LOGGER = logging.getLogger("ptz_control.web")


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
    return JSONResponse(payload)


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
