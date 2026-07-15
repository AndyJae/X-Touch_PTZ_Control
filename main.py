from __future__ import annotations

import logging
from pathlib import Path

import yaml

from core.bus import EventBus
from core.state import StateStore
from midi.surface import Surface


LOGGER = logging.getLogger("ptz_control")


def load_config(path: str | Path = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def build_app() -> tuple[EventBus, StateStore, Surface]:
    event_bus = EventBus()
    state_store = StateStore()
    surface = Surface(state_store=state_store, event_bus=event_bus)
    return event_bus, state_store, surface


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    LOGGER.info("PTZ Control application starting")

    config = load_config()
    event_bus, state_store, surface = build_app()

    for channel_index, camera in enumerate(config.get("cameras", [])[:8], start=1):
        camera_id = camera.get("id", f"cam{channel_index}")
        camera_name = camera.get("name", camera_id)
        surface.bind_camera(channel_index, camera_id=camera_id, name=camera_name)
        state_store.update_channel(channel_index, value=0.0, source="boot")

    surface.set_channel_value(1, 0.5, source="boot")
    surface.set_touch_state(1, False)

    LOGGER.info("Loaded config with %d camera entries", len(config.get("cameras", [])))
    LOGGER.info("Surface channels initialized: %d", len(surface.channels))
    LOGGER.info("State snapshot ready: %s", state_store.snapshot())


if __name__ == "__main__":
    main()
