from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CameraState:
    iris: float | None = None
    iris_f_number: str | None = None
    auto_iris: bool | None = None
    gain_db: int | None = None
    pedestal: int | None = None
    nd_index: int | None = None
    bars: bool | None = None
    error: str | None = None
    # Feature-Button-Zustand (Spec §9a), Schlüssel = Feature-Key aus
    # PanasonicAWDriver.BUTTON_FEATURES: bool für Toggles, int (Cycle-Index)
    # für Cycle-Features. NICHT kamera-verifiziert -- die zugrundeliegenden
    # Kommandos haben keine Query-Gegenstücke (auch in der Referenzquelle
    # smart-reset-browser nicht), Zustand ist rein lokal getrackt und geht
    # bei Reconnect/Neustart auf den Default (nicht gesetzt) zurück.
    feature_states: dict[str, bool | int] = field(default_factory=dict)


@dataclass
class ChannelState:
    channel_index: int
    name: str = ""
    camera_id: str | None = None
    function: str = "iris"
    value: float = 0.0
    touch_active: bool = False
    last_source: str = "unknown"
    button_states: dict[str, bool] = field(default_factory=dict)


class StateStore:
    def __init__(self) -> None:
        self._camera_states: dict[str, CameraState] = {}
        self._channel_states: dict[int, ChannelState] = {}

    def get_camera(self, camera_id: str) -> CameraState:
        return self._camera_states.setdefault(camera_id, CameraState())

    def set_camera(self, camera_id: str, state: CameraState) -> None:
        self._camera_states[camera_id] = state

    def get_channel(self, channel_index: int) -> ChannelState:
        return self._channel_states.setdefault(channel_index, ChannelState(channel_index=channel_index))

    def update_channel(
        self,
        channel_index: int,
        *,
        value: float | None = None,
        camera_id: str | None = None,
        function: str | None = None,
        name: str | None = None,
        touch_active: bool | None = None,
        source: str = "system",
        button_states: dict[str, bool] | None = None,
    ) -> ChannelState:
        channel = self.get_channel(channel_index)
        if value is not None:
            channel.value = value
        if camera_id is not None:
            channel.camera_id = camera_id
        if function is not None:
            channel.function = function
        if name is not None:
            channel.name = name
        if touch_active is not None:
            channel.touch_active = touch_active
        if button_states is not None:
            channel.button_states = button_states
        channel.last_source = source
        return channel

    def snapshot(self) -> dict[str, object]:
        return {
            "channels": {index: vars(state) for index, state in sorted(self._channel_states.items())},
            "cameras": {camera_id: vars(state) for camera_id, state in self._camera_states.items()},
        }
