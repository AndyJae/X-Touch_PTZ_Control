"""web/app.py -- Interface layer: FastAPI routes, WebSocket, templates.

Contains no domain/application logic (driver wiring, mapping->rate
limiter->driver flow, state building) -- that lives in `core/application.py`
and is testable independently of this module. This module only translates
between HTTP/WebSocket and those use cases.
"""

from __future__ import annotations

import asyncio
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
    reset_to_new_config,
    trigger_companion_select,
)
from core.companion import CompanionError, is_reachable
from core.config import load_config
from core.log_buffer import LOG_BUFFER
from midi.fader import XTouchFader

LOGGER = logging.getLogger("ptz_control.web")

_CONFIG_PATH = "config.yaml"

# Real X-Touch Extender ports are named "X-Touch-Ext 0"/"X-Touch-Ext 1" --
# used as the auto-detection default when config.yaml doesn't specify a port.
_AUTO_DETECT_MIDI_SUBSTRING = "X-Touch-Ext"


def _find_midi_port(names: list[str], substring: str) -> str | None:
    """Substring match against the available MIDI port names."""
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
    # The web UI always starts, even if cameras are missing/unreachable --
    # errors are logged per camera, the process never aborts. Cameras are
    # connected concurrently (not sequentially): each camera is independent
    # (its own driver/state entry), so a hanging/failing connect doesn't
    # block the others.
    async def _connect_camera_defensively(camera_id: str) -> None:
        try:
            await connect_camera(state, camera_id)
        except Exception as exc:  # defensive: startup must never fail on a camera
            LOGGER.warning("Kamera %s: Connect fehlgeschlagen: %s", camera_id, exc)
            state.state_store.get_camera(camera_id).error = str(exc)

    await asyncio.gather(*(_connect_camera_defensively(cid) for cid in state.drivers))
    LOGGER.info("X-Touch PTZ Control Web-UI bereit: %d Kamera(s) konfiguriert", len(state.drivers))

    # config.yaml can contain a Companion host without Companion actually
    # running -- confirm real reachability at startup, same as camera connect
    # above.
    if state.config.companion.host:
        state.companion_connected = await is_reachable(
            state.companion_client, state.config.companion.host, state.config.companion.port
        )
        if not state.companion_connected:
            LOGGER.warning(
                "Companion (%s:%s) nicht erreichbar",
                state.config.companion.host,
                state.config.companion.port,
            )

    midi_fader: XTouchFader | None = None
    # An explicitly configured port takes precedence; otherwise auto-detect
    # by the known Behringer X-Touch Extender port name. This is a one-time
    # scan at startup, not hotplug/live-reconnect -- the X-Touch must already
    # be connected via USB before the app starts.
    if config.midi.input_port:
        input_port_substring = config.midi.input_port
        output_port_substring = config.midi.output_port
    else:
        input_port_substring = _AUTO_DETECT_MIDI_SUBSTRING
        output_port_substring = _AUTO_DETECT_MIDI_SUBSTRING
    input_port_name = _find_midi_port(mido.get_input_names(), input_port_substring)
    if input_port_name is not None:
        output_port_name = (
            _find_midi_port(mido.get_output_names(), output_port_substring)
            if output_port_substring
            else None
        )
        midi_fader = XTouchFader(state, input_port_name, output_port_name)
        await midi_fader.start()
    else:
        LOGGER.warning("MIDI-Eingangsport %r nicht gefunden", input_port_substring)

    yield
    for driver in state.drivers.values():
        await driver.disconnect()
    await state.companion_client.aclose()
    if midi_fader is not None:
        await midi_fader.stop()


app = FastAPI(title="X-Touch PTZ Control", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="web/static"), name="static")

templates = Jinja2Templates(directory="web/templates")


def _ptz_state(request: Request) -> AppState:
    return request.app.state.ptz


@app.get("/api/startup/status")
async def api_startup_status(request: Request) -> JSONResponse:
    """Startup dialog ("Load previous config"/"Start new config"), polled by
    the frontend on every page load. `pending` stays `True` until one of the
    two actions below is called, then `False` for the rest of the process."""
    return JSONResponse({"pending": _ptz_state(request).startup_choice_pending})


@app.post("/api/startup/load-previous")
async def api_startup_load_previous(request: Request) -> JSONResponse:
    """"Load previous config": no reset needed -- the app already connected
    normally to the last saved config.yaml at boot; this just marks the
    dialog as answered."""
    _ptz_state(request).startup_choice_pending = False
    return JSONResponse({"ok": True})


@app.post("/api/startup/new-config")
async def api_startup_new_config(request: Request) -> JSONResponse:
    """"Start new config": disconnects every camera connected at boot and
    resets config.yaml to schema defaults."""
    state = _ptz_state(request)
    await reset_to_new_config(state)
    state.startup_choice_pending = False
    return JSONResponse({"ok": True})


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
            "companion_connected": state.companion_connected,
        },
    )


@app.get("/help", response_class=HTMLResponse)
async def help_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="help.html",
        context={"active_page": "help"},
    )


_LOG_LEVELS = ["ALL", "DEBUG", "INFO", "WARNING", "ERROR"]


@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request) -> HTMLResponse:
    """Last 200 log lines, filterable by level. `level=ALL` shows
    everything, any other value shows that level and more severe ones."""
    selected_level = request.query_params.get("level", "ALL").upper()
    if selected_level not in _LOG_LEVELS:
        selected_level = "ALL"
    min_level = (
        logging.getLevelNamesMapping()[selected_level] if selected_level != "ALL" else logging.DEBUG
    )
    return templates.TemplateResponse(
        request=request,
        name="logs.html",
        context={
            "active_page": "logs",
            "levels": _LOG_LEVELS,
            "selected_level": selected_level,
            "entries": LOG_BUFFER.entries(min_level),
        },
    )


@app.post("/api/channels/{channel_index}/camera/disconnect")
async def api_disconnect_camera(channel_index: int, request: Request) -> JSONResponse:
    """Disconnects a channel's camera and removes its registration entirely
    from config.yaml, see disconnect_camera()."""
    state = _ptz_state(request)
    entry = state.mapping.get_channel("fader", channel_index)
    if entry is None:
        return JSONResponse({"error": "kein Kanal/keine Kamera"}, status_code=404)
    await disconnect_camera(state, entry.camera_id)
    return JSONResponse({"connected": False})


@app.post("/api/channels/{channel_index}/camera")
async def api_register_camera(channel_index: int, request: Request) -> JSONResponse:
    """Registers or updates a channel's camera from the Setup page's
    "Connect Camera" form."""
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
    """Updates only the display name, independent of the connect/disconnect
    toggle, see rename_camera()."""
    state = _ptz_state(request)
    body = await request.json()
    name = str(body.get("name") or "")
    await rename_camera(state, channel_index, name)
    return JSONResponse({"ok": True})


@app.get("/api/channels/{channel_index}/available-buttons")
async def api_available_channel_buttons(channel_index: int, request: Request) -> JSONResponse:
    """Feature catalog of the channel's connected camera model (`key ->
    label`), for the gear popover on the overview page. Empty if the
    channel has no (connected) camera."""
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
    """Web UI equivalent of button 1 (Rec) on the X-Touch Extender: cycles
    the channel's encoder function locally."""
    state = _ptz_state(request)
    function_name = await cycle_encoder_function(state, channel_index)
    return JSONResponse({"function": function_name})


@app.post("/api/companion/config")
async def api_configure_companion(request: Request) -> JSONResponse:
    """Configures the single global Bitfocus Companion instance shared
    across all channels."""
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
    # Empty host (disconnect) -> not connected; a set host had its
    # reachability confirmed above already.
    await configure_companion(state, host, port, connected=bool(host))
    return JSONResponse({"ok": True})


@app.post("/api/channels/{channel_index}/companion")
async def api_assign_channel_companion(channel_index: int, request: Request) -> JSONResponse:
    """A channel's SELECT button target (Companion page/row/column), see
    assign_channel_companion_target(). Empty values clear the assignment."""
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
                # apply_encoder_turn() publishes no event bus event (that
                # would trigger a full scribble-strip refresh on MIDI too),
                # so broadcast to WS clients directly here.
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
