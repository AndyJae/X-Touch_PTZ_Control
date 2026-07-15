from __future__ import annotations

import logging
from pathlib import Path

import yaml


LOGGER = logging.getLogger("behringer_ptz")


def load_config(path: str | Path = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    LOGGER.info("Behringer_PTZ development scaffold started")
    config = load_config()
    LOGGER.info("Loaded config with %d camera entries", len(config.get("cameras", [])))


if __name__ == "__main__":
    main()
