from __future__ import annotations

import logging

import uvicorn

from web.app import app, load_config

LOGGER = logging.getLogger("ptz_control")


def main() -> None:
    config = load_config()
    log_level_name = str((config.get("global") or {}).get("log_level", "INFO")).upper()
    logging.basicConfig(level=getattr(logging, log_level_name, logging.INFO))

    # Bind-Adresse: Spec §10 "Bind auf 0.0.0.0 per Config abschaltbar
    # (127.0.0.1 Default)" -- ein Config-Feld dafuer ist im Schema (§4) nicht
    # definiert, daher hier fest der dokumentierte Default. Web-UI startet
    # laut Spec §11 Schritt 2 immer, auch ohne MIDI/Kameras -- die eigentliche
    # Komponenten-Verdrahtung (Treiber, Mapping, Rate-Limiter) passiert im
    # FastAPI-Lifespan von `web.app`, siehe dort.
    port = int((config.get("global") or {}).get("web_port", 8600))
    LOGGER.info("PTZ Control startet Web-UI auf 127.0.0.1:%d", port)
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
