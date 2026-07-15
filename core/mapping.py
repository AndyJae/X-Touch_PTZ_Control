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

    def channels_for_type(self, element_type: str) -> dict[int, ChannelMap]:
        return {
            index: mapping
            for (etype, index), mapping in self._channels.items()
            if etype == element_type
        }


def build_mapping_from_config(config: dict) -> MappingEngine:
    """Baut die Mapping-Engine aus `banks` + `channel_defaults`, Spec §9.

    v1: nur die erste Bank ist aktiv (kein Bank-Switch-UI in diesem Schritt,
    siehe Spec §9 "Bank-Wechsel ... Hardware-Taste gibt es am Extender nicht").
    Fader-Funktion ist laut Spec §4 v1 fix `iris` — kommt aus
    `channel_defaults.fader`, nicht pro Kanal ueberschreibbar in diesem Schritt.
    """
    engine = MappingEngine()
    banks = config.get("banks") or []
    if not banks:
        return engine
    fader_function = (config.get("channel_defaults") or {}).get("fader", "iris")
    channels = banks[0].get("channels") or []
    for index, entry in enumerate(channels, start=1):
        camera_id = (entry or {}).get("camera")
        if camera_id:
            engine.set_channel("fader", index, camera_id, fader_function)
    return engine
