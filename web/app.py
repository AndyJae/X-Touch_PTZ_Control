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

import mido
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.application import (
    AppState,
    apply_button_action,
    apply_encoder_turn,
    apply_iris,
    assign_channel_button,
    assign_channel_companion_target,
    available_button_features,
    build_app_state,
    channel_snapshot,
    commit_encoder_value,
    configure_companion,
    connect_camera,
    cycle_encoder_function,
    disconnect_camera,
    register_camera,
    rename_camera,
    trigger_companion_select,
)
from core.companion import CompanionError, is_reachable
from core.config import load_config
from midi.fader import XTouchFader

LOGGER = logging.getLogger("ptz_control.web")

_CONFIG_PATH = "config.yaml"


def _find_midi_port(names: list[str], substring: str) -> str | None:
    """Spec §5.5: Substring-Match gegen die verfuegbaren Ports."""
    matches = [name for name in names if substring.lower() in name.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        LOGGER.warning("MIDI-Port %r ist mehrdeutig (%s), verbinde nicht", substring, matches)
    return None


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

    midi_fader: XTouchFader | None = None
    # Spec §5.5: ohne konfigurierten Port wartet das Tool (UI-Auswahl folgt in
    # einem spaeteren Schritt) -- kein Auto-Connect ohne explizite Config.
    if config.midi.input_port:
        input_port_name = _find_midi_port(mido.get_input_names(), config.midi.input_port)
        if input_port_name is not None:
            output_port_name = (
                _find_midi_port(mido.get_output_names(), config.midi.output_port)
                if config.midi.output_port
                else None
            )
            midi_fader = XTouchFader(state, input_port_name, output_port_name)
            await midi_fader.start()
        else:
            LOGGER.warning("MIDI-Eingangsport %r nicht gefunden", config.midi.input_port)

    yield
    for driver in state.drivers.values():
        await driver.disconnect()
    await state.companion_client.aclose()
    if midi_fader is not None:
        await midi_fader.stop()


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


@app.get("/api/channels/{channel_index}/available-buttons")
async def api_available_channel_buttons(channel_index: int, request: Request) -> JSONResponse:
    """Feature-Katalog des am Kanal verbundenen Kameramodells (`key -> Label`,
    siehe `available_button_features()`) -- fuer das Zahnrad-Popover auf der
    Übersicht-Seite (Nutzerauftrag 2026-07-18: Funktion direkt dort waehlen
    koennen, ohne auf die Setup-Seite wechseln zu muessen). Leer, wenn der
    Kanal keine (verbundene) Kamera hat."""
    state = _ptz_state(request)
    entry = state.mapping.get_channel("fader", channel_index)
    if entry is None:
        return JSONResponse({"features": {}})
    return JSONResponse({"features": available_button_features(state, entry.camera_id)})


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


@app.post("/api/channels/{channel_index}/encoder/select")
async def api_select_encoder_function(channel_index: int, request: Request) -> JSONResponse:
    """Web-UI-Aequivalent zu Button 1 (physisch Rec) am X-Touch Extender:
    schaltet die Encoder-Funktion des Kanals lokal weiter (Spec §9,
    Nutzerentscheid: Drehregler soll auch im Browser bedienbar sein)."""
    state = _ptz_state(request)
    function_name = await cycle_encoder_function(state, channel_index)
    return JSONResponse({"function": function_name})


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
    if host and not await is_reachable(state.companion_client, host, port):
        return JSONResponse(
            {"error": f"Unter {host}:{port} ist kein Server erreichbar"}, status_code=502
        )
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
            elif message.get("type") == "encoder_turn":
                # `apply_encoder_turn` publiziert bewusst kein EventBus-Event
                # (sonst wuerde jeder Dreh-Tick auch bei MIDI einen vollen
                # 8-Strip-Scribble-Refresh ausloesen, siehe midi/fader.py) --
                # daher hier direkt an alle WS-Clients broadcasten.
                channel_index = int(message["channel"])
                delta = int(message["delta"])
                await apply_encoder_turn(state, channel_index, delta)
                await state.broadcast({"type": "snapshot", "channels": channel_snapshot(state)})
            elif message.get("type") == "encoder_commit":
                channel_index = int(message["channel"])
                await commit_encoder_value(state, channel_index)
                await state.broadcast({"type": "snapshot", "channels": channel_snapshot(state)})
    except WebSocketDisconnect:
        pass
    finally:
        state.ws_clients.discard(websocket)
