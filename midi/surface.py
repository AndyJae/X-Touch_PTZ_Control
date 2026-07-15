from __future__ import annotations

from dataclasses import dataclass, field

from core.bus import EventBus
from core.state import StateStore


@dataclass
class FaderChannel:
    index: int
    name: str = ""
    camera_id: str | None = None
    value: float = 0.0
    touch_active: bool = False
    button_states: dict[str, bool] = field(default_factory=dict)


class Surface:
    def __init__(self, state_store: StateStore | None = None, event_bus: EventBus | None = None) -> None:
        self.state_store = state_store or StateStore()
        self.event_bus = event_bus or EventBus()
        self.channels = [FaderChannel(index=i + 1) for i in range(8)]

    def bind_camera(self, channel_index: int, camera_id: str, name: str) -> None:
        if 1 <= channel_index <= len(self.channels):
            channel = self.channels[channel_index - 1]
            channel.camera_id = camera_id
            channel.name = name
            self.state_store.update_channel(
                channel_index,
                camera_id=camera_id,
                name=name,
                function="iris",
            )

    def set_channel_value(self, channel_index: int, value: float, *, source: str = "ui") -> None:
        if 1 <= channel_index <= len(self.channels):
            channel = self.channels[channel_index - 1]
            channel.value = value
            self.state_store.update_channel(channel_index, value=value, source=source)
            self.event_bus.publish(
                "channel.value_changed",
                {
                    "channel_index": channel_index,
                    "camera_id": channel.camera_id,
                    "value": value,
                    "source": source,
                },
            )

    def set_touch_state(self, channel_index: int, touch_active: bool) -> None:
        if 1 <= channel_index <= len(self.channels):
            channel = self.channels[channel_index - 1]
            channel.touch_active = touch_active
            self.state_store.update_channel(channel_index, touch_active=touch_active, source="midi")
            self.event_bus.publish(
                "channel.touch_changed",
                {
                    "channel_index": channel_index,
                    "touch_active": touch_active,
                },
            )

    def snapshot(self) -> dict[str, object]:
        return {
            "channels": [
                {
                    "index": channel.index,
                    "name": channel.name,
                    "camera_id": channel.camera_id,
                    "value": channel.value,
                    "touch_active": channel.touch_active,
                }
                for channel in self.channels
            ]
        }
