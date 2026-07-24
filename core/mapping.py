from __future__ import annotations

from dataclasses import dataclass

from core.config import AppConfig


@dataclass
class ChannelMap:
    camera_id: str


class MappingEngine:
    def __init__(self) -> None:
        self._channels: dict[tuple[str, int], ChannelMap] = {}

    def set_channel(self, element_type: str, index: int, camera_id: str) -> None:
        self._channels[(element_type, index)] = ChannelMap(camera_id=camera_id)

    def unset_channel(self, element_type: str, index: int) -> None:
        self._channels.pop((element_type, index), None)

    def get_channel(self, element_type: str, index: int) -> ChannelMap | None:
        return self._channels.get((element_type, index))

    def channels_for_type(self, element_type: str) -> dict[int, ChannelMap]:
        return {
            index: mapping
            for (etype, index), mapping in self._channels.items()
            if etype == element_type
        }


def build_mapping_from_config(config: AppConfig) -> MappingEngine:
    """Builds the mapping engine from `banks`. Only the first bank is active
    (no bank-switch UI)."""
    engine = MappingEngine()
    if not config.banks:
        return engine
    for index, entry in enumerate(config.banks[0].channels, start=1):
        if entry is not None:
            engine.set_channel("fader", index, entry.camera)
    return engine
