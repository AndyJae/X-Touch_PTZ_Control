from __future__ import annotations

import logging
import sys

import uvicorn

from core.config import ConfigError, load_config
from web.app import app

LOGGER = logging.getLogger("ptz_control")


def main() -> None:
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
    LOGGER.info("PTZ Control startet Web-UI auf 127.0.0.1:%d", port)
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
