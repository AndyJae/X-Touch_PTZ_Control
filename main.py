from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
import webbrowser

import pystray
import uvicorn
from PIL import Image

from core.config import ConfigError, load_config
from web.app import app

LOGGER = logging.getLogger("ptz_control")

# System-Tray-Verhalten (Nutzerentscheid 2026-07-19): 1:1 nach dem bereits
# umgesetzten Vorbild in C:\smart_reset_work\web_main.py portiert (Mutex,
# Tray-Icon-Aufbau, Windows-11-Patch, Force-Exit-Reihenfolge), an PTZ_Control
# angepasst (Icon-Pfad, Mutex-Name, dynamischer Port statt fest 8765).
_MUTEX_NAME = "Global\\PTZControlApp_SingleInstance"
_ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Images", "Icon.ico")
# Sicherheitsnetz fuer den Browser-Oeffnen-Poll (siehe _open_browser() in
# main()) -- deutlich ueber der worst-case Lifespan-Startzeit bei mehreren
# nicht erreichbaren Kameras (je bis zu ~1,5s Timeout + 1 Retry pro Query).
_BROWSER_OPEN_TIMEOUT = 30.0


def _ensure_single_instance() -> None:
    """Windows-Mutex -- verhindert einen zweiten Prozess, der denselben
    Web-/MIDI-Port beanspruchen würde. Siehe smart_reset_work/web_main.py."""
    ctypes.windll.kernel32.CreateMutexW(None, True, _MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.user32.MessageBoxW(
            None,
            "X-Touch PTZ Control läuft bereits.\nSiehe System Tray.",
            "Bereits gestartet",
            0x40 | 0x1000,  # MB_ICONINFORMATION | MB_SYSTEMMODAL
        )
        sys.exit(0)


def _patch_pystray_win11() -> None:
    """pystray ruft vor TrackPopupMenuEx SetForegroundWindow auf, was unter
    Windows 11 ohne kürzliche Nutzereingabe des Threads stillschweigend
    fehlschlägt -- das Kontextmenü erscheint dann, reagiert aber nicht auf
    Klicks. Siehe smart_reset_work/web_main.py."""
    try:
        import pystray._win32 as _backend

        _WM_RBUTTONUP = 0x0205
        _orig = _backend.Icon._on_notify

        def _fixed(self, wparam, lparam):
            if lparam == _WM_RBUTTONUP:
                ctypes.windll.user32.keybd_event(0, 0, 0, 0)
            return _orig(self, wparam, lparam)

        _backend.Icon._on_notify = _fixed
    except Exception:
        pass


def main() -> None:
    _ensure_single_instance()
    _patch_pystray_win11()

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Ungültige config.yaml: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    log_level_name = config.global_.log_level.upper()
    logging.basicConfig(level=getattr(logging, log_level_name, logging.INFO))

    # Bind-Adresse: Spec §10 "Bind auf 0.0.0.0 per Config abschaltbar
    # (127.0.0.1 Default)" -- ein Config-Feld dafuer ist im Schema (§4) nicht
    # definiert, daher hier fest der dokumentierte Default. Web-UI startet
    # laut Spec §11 Schritt 2 immer, auch ohne MIDI/Kameras -- die eigentliche
    # Komponenten-Verdrahtung (Treiber, Mapping, Rate-Limiter) passiert im
    # FastAPI-Lifespan von `web.app`, siehe dort.
    port = config.global_.web_port
    url = f"http://127.0.0.1:{port}"
    LOGGER.info("X-Touch PTZ Control startet Web-UI auf 127.0.0.1:%d", port)

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))

    def _open_browser() -> None:
        # Bugreport 2026-07-22: die vorherige feste `time.sleep(1.2)` ging
        # von einer kurzen, konstanten Startzeit aus -- der FastAPI-Lifespan
        # (web/app.py) verbindet aber sequenziell JEDE konfigurierte Kamera
        # (je bis zu ~1,5s Timeout + 1 Retry pro Query, §7.4), was bei
        # mehreren nicht erreichbaren Kameras die Startzeit weit über 1,2s
        # treiben kann -- der Browser oeffnete sich dann, bevor der Server
        # ueberhaupt auf dem Port lauschte. `server.started` wird von uvicorn
        # erst NACH dem vollstaendigen Lifespan-Startup auf `True` gesetzt --
        # kurzes Polling darauf statt einer geratenen festen Wartezeit.
        # `_BROWSER_OPEN_TIMEOUT` ist nur ein Sicherheitsnetz, falls der
        # Server nie startet (z. B. Port belegt) -- der Browser oeffnet sich
        # dann trotzdem, wie schon vorher.
        deadline = time.monotonic() + _BROWSER_OPEN_TIMEOUT
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        webbrowser.open(url)

    # uvicorn und Browser-Öffnen laufen im Hintergrund-Thread, der Hauptthread
    # ist für das Tray-Icon reserviert (Windows-Anforderung, siehe
    # smart_reset_work/web_main.py).
    threading.Thread(target=server.run, daemon=True).start()
    threading.Thread(target=_open_browser, daemon=True).start()

    def on_open(_icon, _item):
        webbrowser.open(url)

    def on_quit(icon, _item):
        try:
            server.should_exit = True
            icon.stop()
        finally:
            os._exit(0)

    try:
        tray = pystray.Icon(
            "ptz-control",
            Image.open(_ICON_PATH),
            "X-Touch PTZ Control",
            menu=pystray.Menu(
                pystray.MenuItem("Open", on_open, default=True),
                pystray.MenuItem("Quit", on_quit),
            ),
        )
        tray.run()  # blockiert, bis on_quit icon.stop() aufruft
    except Exception as exc:
        ctypes.windll.user32.MessageBoxW(
            None,
            f"X-Touch PTZ Control konnte kein System-Tray-Icon erstellen:\n\n{exc}\n\n"
            f"Der Server läuft weiter. {url} manuell öffnen.",
            "X-Touch PTZ Control — Tray-Fehler",
            0x10 | 0x1000,  # MB_ICONERROR | MB_SYSTEMMODAL
        )
    finally:
        # Force-Exit, damit der Prozess sofort terminiert und den
        # Single-Instance-Mutex freigibt -- ohne das können pystrays
        # Windows-Backend oder uvicorns Graceful-Shutdown-Thread den Prozess
        # nach Tray-Ende am Leben halten (naechster Start meldet dann
        # faelschlich "läuft bereits").
        os._exit(0)


if __name__ == "__main__":
    main()
