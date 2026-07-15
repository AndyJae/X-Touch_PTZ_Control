from __future__ import annotations

from collections.abc import Callable

from drivers.base import CameraDriver


class PanasonicAWDriver(CameraDriver):
    def __init__(self, host: str, port: int = 80) -> None:
        self.host = host
        self.port = port
        self._connected = False

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def set_iris(self, value: float) -> None:
        _ = value

    async def set_auto_iris(self, on: bool) -> None:
        _ = on

    async def set_gain_db(self, db: int) -> None:
        _ = db

    async def step_gain(self, delta_db: int) -> int:
        return delta_db

    async def set_pedestal(self, value: int) -> None:
        _ = value

    async def set_rb_gain(self, r: int | None, b: int | None) -> None:
        _ = (r, b)

    async def set_nd(self, index: int) -> None:
        _ = index

    async def cycle_nd(self) -> int:
        return 0

    async def set_shutter(self, mode: str, value: int | None) -> None:
        _ = (mode, value)

    async def trigger_awb(self) -> None:
        return None

    async def set_bars(self, on: bool) -> None:
        _ = on

    async def recall_preset(self, number: int) -> None:
        _ = number

    async def get_state(self) -> dict:
        return {}

    def subscribe(self, callback: Callable[[dict], None]) -> None:
        _ = callback
