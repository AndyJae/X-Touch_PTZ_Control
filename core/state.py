from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CameraState:
    iris: float | None = None
    iris_f_number: str | None = None
    auto_iris: bool | None = None
    gain_db: int | None = None
    # None = unknown, True = Auto/AGC active, False = manual mode (gain_db valid).
    gain_auto: bool | None = None
    pedestal: int | None = None
    nd_index: int | None = None
    error: str | None = None
    # Toggle-button feature state, keyed by feature key from
    # PanasonicAWDriver.BUTTON_FEATURES. Starts empty on every reconnect
    # (get_state() returns a fresh CameraState) but core/application.py's
    # connect_camera() re-queries it right away for any feature already
    # assigned to a button2/button3 slot, via query_button_feature().
    feature_states: dict[str, bool | int] = field(default_factory=dict)


class StateStore:
    def __init__(self) -> None:
        self._camera_states: dict[str, CameraState] = {}

    def get_camera(self, camera_id: str) -> CameraState:
        return self._camera_states.setdefault(camera_id, CameraState())

    def set_camera(self, camera_id: str, state: CameraState) -> None:
        self._camera_states[camera_id] = state
