from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CameraState:
    iris: float | None = None
    iris_f_number: str | None = None
    auto_iris: bool | None = None
    gain_db: int | None = None
    nd_index: int | None = None
    shutter: str | None = None
    bars: bool | None = None
    error: str | None = None


class StateStore:
    def __init__(self) -> None:
        self._camera_states: dict[str, CameraState] = {}

    def get(self, camera_id: str) -> CameraState:
        return self._camera_states.setdefault(camera_id, CameraState())

    def set(self, camera_id: str, state: CameraState) -> None:
        self._camera_states[camera_id] = state
