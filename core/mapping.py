from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ChannelMap:
    camera_id: str
    function: str


class MappingEngine:
    def __init__(self) -> None:
        self._channels: dict[tuple[str, int], ChannelMap] = {}

    def set_channel(self, element_type: str, index: int, camera_id: str, function: str) -> None:
        self._channels[(element_type, index)] = ChannelMap(camera_id=camera_id, function=function)

    def get_channel(self, element_type: str, index: int) -> ChannelMap | None:
        return self._channels.get((element_type, index))
