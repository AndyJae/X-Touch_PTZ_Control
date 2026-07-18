"""
tools/panasonic_emulator.py -- Lokaler Panasonic-CGI-Emulator (Dev-Werkzeug,
kein Produktionscode). Nachbildung der HTTP/CGI-Strecke, gegen die
`drivers/panasonic_aw.py` real spricht, damit die Web-UI-Verdrahtung ohne
reale Kamera durchgetestet werden kann.

Design angelehnt an C:\\smart_reset_work\\tools\\panasonic_emulator.py
(Zwei-Server-Prozess: Control-UI zum Start/Stop + CGI-Server), aber
eigenstaendig. Wichtigster Unterschied: die dort generische, Doppelpunkt-
basierte Dispatch-Logik deckt die Doppelpunkt-losen `ptz`-Typ-Befehle
(`#AXI`, `#GI`, `#R`) nicht ab, die dieser Treiber fuer die Iris-Steuerung
tatsaechlich nutzt -- hier werden sie explizit behandelt.

**Modell-Auswahl (Nutzerentscheid 2026-07-18):** Das simulierte Kameramodell
wird im Start-Formular der Control-UI aus allen in
`drivers/panasonic_models/` registrierten Modellen ausgewaehlt (Standard
AW-UE160, per `--model` vorbelegbar wie `--port`). Das gewaehlte Modell
bestimmt:
  - die `QID`-Antwort,
  - ob `OGU`/`QGU` (Gain) ueberhaupt akzeptiert wird -- Modelle ohne
    `GAIN_MIN_DB`/`GAIN_MAX_DB` (z. B. AK-UB300, dessen Gain strukturell
    anders funktioniert, oder Modelle ohne Eintrag in den beiden Referenz-
    PDFs) liefern `ER1`, wie eine echte Kamera ohne dieses Kommando,
  - welche Pedestal-Kommandofamilie bedient wird (`OSJ:0F`/`OTP`/`OSG:4A`,
    je nach `PEDESTAL_COMMAND` des Modells) bzw. `ER1`, wenn das Modell
    keine Pedestal-Daten hat,
  - welche Kamera-Feature-Button-Befehle akzeptiert werden -- nur die im
    Modell-Katalog (`BUTTON_FEATURES`) tatsaechlich vorkommenden Kommandos,
    alles andere liefert `ER1` (z. B. hat AW-HE50 keinen "knee"-Befehl).
Iris/ND/Bars/Fehlerstatus/F-Nummer bleiben modellunabhaengig (kein
per-Modell-Daten dafuer vorhanden, siehe CLAUDE.md Offene Punkte).

Nur die vom Treiber tatsaechlich gesendeten Befehle sind abgedeckt (siehe
`drivers/panasonic_aw.py`); alles andere liefert ER1 (unbekannter Befehl),
analog zur echten Kamera. ER2/ER3 (busy/out-of-range) werden NICHT simuliert
-- bekannte Luecke, siehe Docstring von `_handle_cam`.

Zwei Server in einem Prozess:
  - Control-UI (immer erreichbar auf --ui-port): Modell/Port waehlen, Start/Stop.
    Stop gibt den Kamera-Port tatsaechlich frei, ein Connect-Versuch waehrend
    "gestoppt" bekommt ein echtes Connection-Refused, wie bei einer
    ausgeschalteten Kamera.
  - Kamera-CGI-Server (--port): hoert nur, waehrend "gestartet".

Start:
    python tools/panasonic_emulator.py [--ui-port 8080] [--port 8081] [--model AW-UE160]
Dann http://127.0.0.1:<ui-port>/ oeffnen, Modell/Port waehlen, "Server starten".
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path
from types import ModuleType

import uvicorn
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

# `python tools/panasonic_emulator.py` (siehe Modul-Docstring "Start") setzt
# sys.path[0] auf `tools/`, nicht auf das Repo-Root -- ohne diesen Bootstrap
# waere `drivers.panasonic_models` (fuer die Modell-Auswahl) nicht importierbar.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drivers.panasonic_models.registry import get_registry, resolve_model  # noqa: E402

# Gain-Anker (Data = 0x08 + dB, 0x80 = AGC) ist laut beiden lokalen
# Referenz-PDFs modelluebergreifend identisch (siehe
# drivers/panasonic_aw.py::_GAIN_ZERO_DB_DATA) -- nur ob ein Modell OGU
# ueberhaupt unterstuetzt (GAIN_MIN_DB/GAIN_MAX_DB vorhanden) ist modellabhaengig.
_GAIN_ZERO_DB_DATA = 0x08

DEFAULT_MODEL_ID = "AW-UE160"


def _model_button_commands(module: ModuleType | None) -> set[str]:
    """Flache Menge aller literalen Kommandos aus `module.BUTTON_FEATURES`
    (siehe drivers/panasonic_aw.py::trigger_button_feature/
    cycle_button_feature fuer die Struktur) -- nur diese Kommandos werden
    fuer das jeweilige Modell als Kamera-Feature-Button akzeptiert."""
    commands: set[str] = set()
    for feature in getattr(module, "BUTTON_FEATURES", {}).values():
        kind = feature["kind"]
        if kind == "toggle":
            commands.add(feature["on"])
            commands.add(feature["off"])
        elif kind == "trigger":
            commands.add(feature["cmd"])
        elif kind == "cycle":
            for step in feature["cycle"]:
                commands.update(step["cmd"])
    return commands


class CameraState:
    """Haelt den simulierten Geraetezustand fuer ein bestimmtes Kameramodell.
    Startwerte sind willkuerlich gewaehlte, gueltige Werte innerhalb der
    jeweiligen Spec-Range -- keine behaupteten Werkseinstellungen der echten
    Kamera (die sind nicht bekannt)."""

    def __init__(self, model_id: str = DEFAULT_MODEL_ID) -> None:
        self.model_id = model_id
        module = resolve_model(model_id)

        self.iris_data = 0xAAA  # Mitte von 555h-FFFh
        self.auto_iris = False

        self.gain_data = _GAIN_ZERO_DB_DATA  # 0dB
        self.gain_min_db = getattr(module, "GAIN_MIN_DB", None) if module else None
        self.gain_max_db = getattr(module, "GAIN_MAX_DB", None) if module else None

        self.pedestal_command = getattr(module, "PEDESTAL_COMMAND", None) if module else None
        self.pedestal_query_command = getattr(module, "PEDESTAL_QUERY_COMMAND", None) if module else None
        self.pedestal_center_data = getattr(module, "PEDESTAL_CENTER_DATA", None) if module else None
        self.pedestal_scale = getattr(module, "PEDESTAL_SCALE", None) if module else None
        self.pedestal_data_width = getattr(module, "PEDESTAL_DATA_WIDTH", None) if module else None
        self.pedestal_data = self.pedestal_center_data if self.pedestal_center_data is not None else 0

        self.known_button_commands = _model_button_commands(module)

        self.nd_index = 0  # THROUGH
        self.bars_on = False
        self.log: list[str] = []

    def record(self, endpoint: str, cmd: str, response: str) -> None:
        self.log.append(f"{endpoint} {cmd} -> {response}")
        self.log = self.log[-50:]


state = CameraState()


def _handle_cam(cmd: str) -> str:
    """`aw_cam`-Endpunkt: Doppelpunkt-getrennte Befehle, Control-Antwort
    echot den Befehl (spec-bestaetigt fuer OGU/ORS/DCB/OFT/OWS/OAS, siehe
    AW-UE160_InterfaceSpecification_E.pdf Kap.9; Pedestal-Kommando ist
    modellabhaengig, siehe `state.pedestal_command`/Modul-Docstring).

    Bekannte Luecke: ER2 (busy)/ER3 (out-of-range) werden nicht simuliert --
    jeder syntaktisch erkannte Befehl wird akzeptiert, auch mit Werten
    ausserhalb der reglementierten Range.
    """
    cmd = cmd.strip()

    if cmd == "QID":
        return f"OID:{state.model_id}"

    if cmd == "QGU" or cmd.startswith("OGU:"):
        if state.gain_min_db is None or state.gain_max_db is None:
            # Modell hat laut den beiden Referenz-PDFs kein OGU/QGU (z.B.
            # AK-UB300 mit strukturell anderem Gain-Schema, oder ein Modell
            # ohne dokumentierte Gain-Daten) -- wie eine echte Kamera ohne
            # dieses Kommando.
            return f"ER1:{cmd}"
        if cmd == "QGU":
            return f"OGU:{state.gain_data:02X}"
        state.gain_data = int(cmd.split(":", 1)[1], 16)
        return cmd
    if cmd == "QFT":
        return f"OFT:{state.nd_index}"
    if cmd.startswith("OFT:"):
        state.nd_index = int(cmd.split(":", 1)[1])
        return cmd
    if cmd == "QRS":
        return f"ORS:{1 if state.auto_iris else 0}"
    if cmd.startswith("ORS:"):
        state.auto_iris = cmd.split(":", 1)[1] == "1"
        return cmd
    if cmd == "QIF":
        # F-Nummer-Dekodiertabelle ist in der Spec nicht vollstaendig definiert
        # (siehe Spec §14 Punkt 10) -- Anker A0h=F16 als Platzhalter-Antwort.
        return "OIF:A0"
    if cmd == "QER":
        return "OER:0"  # 0 = Normal
    if cmd == "QBR":
        return f"OBR:{1 if state.bars_on else 0}"
    if cmd.startswith("DCB:"):
        state.bars_on = cmd.split(":", 1)[1] == "1"
        return cmd

    if state.pedestal_command is not None:
        if cmd == state.pedestal_query_command:
            return f"{state.pedestal_command}:{state.pedestal_data:0{state.pedestal_data_width}X}"
        prefix = f"{state.pedestal_command}:"
        if cmd.startswith(prefix):
            state.pedestal_data = int(cmd[len(prefix):], 16)
            return cmd
    # Kein `else` noetig -- hat das Modell keine Pedestal-Daten
    # (`state.pedestal_command is None`), faellt jedes Pedestal-Kommando
    # unten durch auf ER1, wie eine echte Kamera ohne dieses Kommando.

    if cmd.startswith("OSL:36:") or cmd.startswith("OSL:38:"):
        return cmd  # R/B Gain Preset: nur echoen
    if cmd in ("OWS", "OAS"):
        return cmd  # AWB/ABB-Trigger: Notification-Verhalten wird hier nicht simuliert
    if cmd in state.known_button_commands:
        # Kamera-Feature-Buttons (Spec §9a, modellabhaengiger Katalog aus
        # drivers/panasonic_models/*.py): nur echoen, kein Folgezustand
        # simuliert -- der Treiber fragt diese Werte nicht ab (keine
        # Query-Kommandos definiert, siehe dortiger Kommentar), also reicht
        # das Echo fuer den Smoke-Test. Kommandos ausserhalb des Katalogs des
        # gewaehlten Modells (z.B. "knee" bei AW-HE50) fallen unten auf ER1,
        # wie bei einer echten Kamera ohne diesen Menuepunkt.
        return cmd

    return f"ER1:{cmd}"


def _handle_ptz(cmd: str) -> str:
    """`aw_ptz`-Endpunkt: Doppelpunkt-lose Befehle -- explizit behandelt,
    weil die generische Doppelpunkt-Logik des `smart_reset_work`-Vorbilds
    diese Befehle nicht abdeckt (siehe Modul-Docstring)."""
    cmd = cmd.strip()

    if cmd.startswith("#AXI") and len(cmd) == 7:
        state.iris_data = int(cmd[4:], 16)
        return f"axi{cmd[4:]}"
    if cmd == "#GI":
        return f"gi{state.iris_data:03x}{1 if state.auto_iris else 0}"
    if cmd.startswith("#R") and len(cmd) == 4 and cmd[2:].isdigit():
        return f"s{cmd[2:]}"

    return f"eR1:{cmd}"


# ---------------------------------------------------------------------------
# Kamera-CGI-Server -- hoert nur, waehrend "gestartet"
# ---------------------------------------------------------------------------

cgi_app = FastAPI()


@cgi_app.get("/cgi-bin/aw_cam")
async def aw_cam(cmd: str = "") -> PlainTextResponse:
    response = _handle_cam(cmd)
    state.record("aw_cam", cmd, response)
    return PlainTextResponse(response)


@cgi_app.get("/cgi-bin/aw_ptz")
async def aw_ptz(cmd: str = "") -> PlainTextResponse:
    response = _handle_ptz(cmd)
    state.record("aw_ptz", cmd, response)
    return PlainTextResponse(response)


class ServerManager:
    """Startet/stoppt den Kamera-CGI-Server (uvicorn) in einem Hintergrund-Thread."""

    def __init__(self) -> None:
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None
        self.host: str = "127.0.0.1"
        self.port: int | None = None
        self.model: str = DEFAULT_MODEL_ID
        self.error: str | None = None

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self, host: str, port: int, model: str) -> None:
        if self.running:
            return
        self.error = None
        self.model = model
        global state
        state = CameraState(model)

        config = uvicorn.Config(cgi_app, host=host, port=port, log_level="warning")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        self.server = server
        self.host = host
        self.port = port
        thread.start()
        self.thread = thread

        for _ in range(60):
            if server.started or not thread.is_alive():
                break
            time.sleep(0.05)

        if not server.started:
            self.error = f"Port {port} konnte nicht gebunden werden (belegt?)."
            self.thread = None
            self.server = None
            self.port = None

    def stop(self) -> None:
        if self.server:
            self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=5)
        self.server = None
        self.thread = None
        self.port = None


manager = ServerManager()


# ---------------------------------------------------------------------------
# Control-UI -- immer erreichbar
# ---------------------------------------------------------------------------

control_app = FastAPI()

_PAGE = """<!doctype html>
<html><head><title>Panasonic CGI-Emulator</title>
<style>
body {{ font-family: sans-serif; max-width: 700px; margin: 2rem auto; padding: 0 1rem; }}
table {{ border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; }}
td, th {{ border: 1px solid #ccc; padding: 4px 8px; text-align: left; font-size: 0.85em; }}
form {{ margin: 1rem 0; }}
label {{ display: block; margin: 0.5rem 0; }}
select {{ font-size: 1em; }}
.error {{ color: #b00020; }}
</style></head>
<body>
<h1>Panasonic CGI-Emulator</h1>
<p>Modell: <b>{model}</b> (siehe `drivers/panasonic_models/`, CLAUDE.md)</p>
{status_block}
{log_state_block}
</body></html>"""

_STOPPED_BLOCK = """<form method="post" action="/start">
<label>Modell:
<select name="model">{model_options}</select>
</label>
<label>Port:
<input type="number" name="port" value="{port}" min="1" max="65535">
</label>
<button type="submit">Server starten</button>
</form>
{error}
<p>Status: <b>gestoppt</b> &mdash; unter dieser Adresse ist aktuell keine Kamera erreichbar.</p>"""

_RUNNING_BLOCK = """<p>Status: <b>läuft</b> &mdash; auf <code>{host}:{port}</code></p>
<form method="post" action="/stop"><button type="submit">Server stoppen</button></form>"""

_LOG_STATE_BLOCK = """<h2>Letzte Befehle</h2>
<table><tr><th>#</th><th>Befehl</th></tr>{log_rows}</table>
<h2>Gespeicherter Zustand</h2>
<table>
<tr><td>Iris (hex)</td><td>{iris:03X}</td></tr>
<tr><td>Auto-Iris</td><td>{auto_iris}</td></tr>
<tr><td>Gain (hex)</td><td>{gain}</td></tr>
<tr><td>Pedestal (hex)</td><td>{pedestal}</td></tr>
<tr><td>ND-Index</td><td>{nd}</td></tr>
<tr><td>Bars</td><td>{bars}</td></tr>
</table>
<p><a href="/">Aktualisieren</a></p>"""


def _model_options(selected: str) -> str:
    options = []
    for camera_id in get_registry().registered_camera_ids():
        marker = " selected" if camera_id == selected else ""
        options.append(f'<option value="{camera_id}"{marker}>{camera_id}</option>')
    return "".join(options)


def _render() -> str:
    if manager.running:
        status_block = _RUNNING_BLOCK.format(host=manager.host, port=manager.port)
        log_rows = "".join(
            f"<tr><td>{i + 1}</td><td>{cmd}</td></tr>"
            for i, cmd in enumerate(reversed(state.log))
        ) or "<tr><td colspan='2'>&mdash;</td></tr>"
        gain_text = f"{state.gain_data:02X}" if state.gain_min_db is not None else "n/a (Modell hat kein OGU)"
        pedestal_text = (
            f"{state.pedestal_data:0{state.pedestal_data_width}X}"
            if state.pedestal_command is not None
            else "n/a (Modell hat kein Pedestal-Kommando)"
        )
        log_state_block = _LOG_STATE_BLOCK.format(
            log_rows=log_rows,
            iris=state.iris_data,
            auto_iris=state.auto_iris,
            gain=gain_text,
            pedestal=pedestal_text,
            nd=state.nd_index,
            bars=state.bars_on,
        )
    else:
        error = f'<p class="error">{manager.error}</p>' if manager.error else ""
        status_block = _STOPPED_BLOCK.format(
            port=manager.port or 8081,
            model_options=_model_options(manager.model),
            error=error,
        )
        log_state_block = ""

    displayed_model = state.model_id if manager.running else manager.model
    return _PAGE.format(model=displayed_model, status_block=status_block, log_state_block=log_state_block)


@control_app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return _render()


@control_app.post("/start")
async def start(port: int = Form(...), model: str = Form(...)) -> RedirectResponse:
    manager.start(manager.host, port, model)
    return RedirectResponse("/", status_code=303)


@control_app.post("/stop")
async def stop() -> RedirectResponse:
    manager.stop()
    return RedirectResponse("/", status_code=303)


def main() -> None:
    parser = argparse.ArgumentParser(description="Panasonic CGI-Emulator (Dev-Werkzeug)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind-Adresse fuer UI und Kamera-Server")
    parser.add_argument("--ui-port", type=int, default=8080, help="Port der Steuer-UI")
    parser.add_argument("--port", type=int, default=8081, help="Vorbelegter Kamera-Port im Start-Formular")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL_ID,
        choices=get_registry().registered_camera_ids(),
        help="Vorbelegtes Kameramodell im Start-Formular (Dropdown, siehe drivers/panasonic_models/)",
    )
    args = parser.parse_args()

    manager.host = args.host
    manager.port = args.port
    manager.model = args.model

    print(f"Panasonic Emulator UI: http://{args.host}:{args.ui_port}/")
    uvicorn.run(control_app, host=args.host, port=args.ui_port, log_level="warning")


if __name__ == "__main__":
    main()
