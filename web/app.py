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
    apply_button_action,
    apply_iris,
    assign_channel_button,
    assign_channel_companion_target,
    available_button_features,
    build_app_state,
    channel_snapshot,
    configure_companion,
    connect_camera,
    disconnect_camera,
    register_camera,
    rename_camera,
    trigger_companion_select,
)
from core.companion import CompanionError
from core.config import load_config

LOGGER = logging.getLogger("ptz_control.web")

_CONFIG_PATH = "config.yaml"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config = load_config(_CONFIG_PATH)
    state = build_app_state(config, config_path=_CONFIG_PATH)
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
    await state.companion_client.aclose()


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
    button_features = {
        camera_id: available_button_features(state, camera_id) for camera_id in state.cameras
    }
    return templates.TemplateResponse(
        request=request,
        name="setup.html",
        context={
            "active_page": "setup",
            "channels": channel_snapshot(state),
            "button_features": button_features,
            "companion": state.config.companion,
        },
    )


@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="config.html", context={"active_page": "config"})


@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="logs.html", context={"active_page": "logs"})


@app.post("/api/channels/{channel_index}/camera/disconnect")
async def api_disconnect_camera(channel_index: int, request: Request) -> JSONResponse:
    """Entkoppelt die Kamera eines Kanals (Setup-Tabelle: "Connect Camera"
    im verbundenen Zustand erneut geklickt). Registrierung in config.yaml
    bleibt bestehen."""
    state = _ptz_state(request)
    entry = state.mapping.get_channel("fader", channel_index)
    if entry is None:
        return JSONResponse({"error": "kein Kanal/keine Kamera"}, status_code=404)
    await disconnect_camera(state, entry.camera_id)
    return JSONResponse({"connected": False})


@app.post("/api/channels/{channel_index}/camera")
async def api_register_camera(channel_index: int, request: Request) -> JSONResponse:
    """Registriert/aktualisiert die Kamera eines Kanals aus der Setup-Tabelle
    ("Connect Camera") -- ersetzt externes Eintragen in config.yaml für
    Kamera-Stammdaten (Nutzerentscheid, Abkehr von Spec §10.3)."""
    state = _ptz_state(request)
    body = await request.json()
    name = str(body.get("name") or "").strip()
    host = str(body.get("host") or "").strip()
    port_raw = body.get("port")
    try:
        port = int(port_raw) if port_raw not in (None, "") else 80
    except (TypeError, ValueError):
        return JSONResponse({"error": f"ungültiger Port: {port_raw!r}"}, status_code=400)
    try:
        await register_camera(state, channel_index, name=name, host=host, port=port)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    entry = state.mapping.get_channel("fader", channel_index)
    driver = state.drivers[entry.camera_id]
    cam_state = state.state_store.get_camera(entry.camera_id)
    return JSONResponse({"connected": driver.connected, "model": driver.model, "error": cam_state.error})


@app.post("/api/channels/{channel_index}/camera/name")
async def api_rename_camera(channel_index: int, request: Request) -> JSONResponse:
    """Aktualisiert nur den Anzeigenamen (Setup-Tabelle: Namensfeld
    verlassen) -- unabhängig vom Connect/Disconnect-Toggle, siehe
    rename_camera()."""
    state = _ptz_state(request)
    body = await request.json()
    name = str(body.get("name") or "")
    await rename_camera(state, channel_index, name)
    return JSONResponse({"ok": True})


@app.post("/api/channels/{channel_index}/buttons/{button_slot}")
async def api_assign_channel_button(channel_index: int, button_slot: str, request: Request) -> JSONResponse:
    state = _ptz_state(request)
    body = await request.json()
    feature_key = body.get("feature_key") or None
    try:
        await assign_channel_button(state, channel_index, button_slot, feature_key)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True})


@app.post("/api/channels/{channel_index}/buttons/{button_slot}/trigger")
async def api_trigger_channel_button(channel_index: int, button_slot: str, request: Request) -> JSONResponse:
    state = _ptz_state(request)
    try:
        await apply_button_action(state, channel_index, button_slot)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True})


@app.post("/api/companion/config")
async def api_configure_companion(request: Request) -> JSONResponse:
    """Globale Bitfocus-Companion-Instanz (eine für alle Kanäle,
    Nutzerentscheid) -- Setup-Panel an der Stelle des ehemaligen "Camera
    Status"-Blocks."""
    state = _ptz_state(request)
    body = await request.json()
    host = str(body.get("host") or "").strip()
    port_raw = body.get("port")
    try:
        port = int(port_raw) if port_raw not in (None, "") else 8000
    except (TypeError, ValueError):
        return JSONResponse({"error": f"ungültiger Port: {port_raw!r}"}, status_code=400)
    await configure_companion(state, host, port)
    return JSONResponse({"ok": True})


@app.post("/api/channels/{channel_index}/companion")
async def api_assign_channel_companion(channel_index: int, request: Request) -> JSONResponse:
    """SELECT-Button-Ziel (Companion Page/Row/Column) eines Kanals, siehe
    assign_channel_companion_target(). Leere Werte löschen die Zuordnung."""
    state = _ptz_state(request)
    body = await request.json()

    def _to_int(value: object) -> int | None:
        if value in (None, ""):
            return None
        return int(value)  # type: ignore[arg-type]

    try:
        page = _to_int(body.get("page"))
        row = _to_int(body.get("row"))
        column = _to_int(body.get("column"))
    except (TypeError, ValueError):
        return JSONResponse({"error": "Page/Row/Column müssen Zahlen sein"}, status_code=400)
    try:
        await assign_channel_companion_target(state, channel_index, page, row, column)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True})


@app.post("/api/channels/{channel_index}/companion/trigger")
async def api_trigger_companion_select(channel_index: int, request: Request) -> JSONResponse:
    state = _ptz_state(request)
    try:
        await trigger_companion_select(state, channel_index)
    except CompanionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    return JSONResponse({"ok": True})


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
