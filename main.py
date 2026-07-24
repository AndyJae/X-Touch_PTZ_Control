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

_MUTEX_NAME = "Global\\PTZControlApp_SingleInstance"
_ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Images", "Icon.ico")
# Safety net for the browser-open poll below -- well above the worst-case
# lifespan startup time with several unreachable cameras.
_BROWSER_OPEN_TIMEOUT = 30.0


def _ensure_single_instance() -> None:
    """Windows mutex -- prevents a second process from claiming the same
    web/MIDI port."""
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
    """pystray calls SetForegroundWindow before TrackPopupMenuEx, which
    silently fails on Windows 11 without recent user input on the thread --
    the context menu then appears but doesn't respond to clicks."""
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

    port = config.global_.web_port
    url = f"http://127.0.0.1:{port}"
    LOGGER.info("X-Touch PTZ Control startet Web-UI auf 127.0.0.1:%d", port)

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))

    def _open_browser() -> None:
        # Polls server.started (set by uvicorn only after the full lifespan
        # startup completes) rather than guessing a fixed delay.
        # _BROWSER_OPEN_TIMEOUT is just a safety net if the server never
        # starts (e.g. port already in use) -- the browser opens anyway.
        deadline = time.monotonic() + _BROWSER_OPEN_TIMEOUT
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        webbrowser.open(url)

    # uvicorn and browser-open run on background threads; the main thread is
    # reserved for the tray icon (Windows requirement).
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
        tray.run()  # blocks until on_quit calls icon.stop()
    except Exception as exc:
        ctypes.windll.user32.MessageBoxW(
            None,
            f"X-Touch PTZ Control konnte kein System-Tray-Icon erstellen:\n\n{exc}\n\n"
            f"Der Server läuft weiter. {url} manuell öffnen.",
            "X-Touch PTZ Control — Tray-Fehler",
            0x10 | 0x1000,  # MB_ICONERROR | MB_SYSTEMMODAL
        )
    finally:
        # Force-exit so the process terminates immediately and releases the
        # single-instance mutex -- without this, pystray's Windows backend
        # or uvicorn's graceful-shutdown thread can keep the process alive
        # after the tray closes.
        os._exit(0)


if __name__ == "__main__":
    main()
