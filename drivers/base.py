from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from core.state import CameraState


class CameraCommandError(Exception):
    """Camera responded with an error code, or is unreachable after retry."""


class CameraDriver(ABC):
    @abstractmethod
    async def connect(self) -> None:
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        ...

    @property
    @abstractmethod
    def connected(self) -> bool:
        ...

    @abstractmethod
    async def set_iris(self, value: float) -> None:
        ...

    @abstractmethod
    async def set_auto_iris(self, on: bool) -> None:
        ...

    @abstractmethod
    async def set_gain_db(self, db: int) -> None:
        ...

    @abstractmethod
    async def step_gain(self, delta_db: int) -> tuple[int | None, bool]:
        """Returns (new dB value or `None` if Auto, is_auto). Auto/AGC is a
        regular third gain state, not an error."""
        ...

    @abstractmethod
    async def set_pedestal(self, value: int) -> None:
        ...

    @abstractmethod
    async def step_pedestal(self, delta: int) -> int:
        ...

    @abstractmethod
    async def set_rb_gain(self, r: int | None, b: int | None) -> None:
        ...

    @abstractmethod
    async def set_nd(self, index: int) -> None:
        ...

    @abstractmethod
    async def cycle_nd(self) -> int:
        ...

    @abstractmethod
    async def trigger_awb(self) -> None:
        ...

    @abstractmethod
    async def set_bars(self, on: bool) -> None:
        ...

    @abstractmethod
    async def recall_preset(self, number: int) -> None:
        ...

    @abstractmethod
    async def get_state(self) -> CameraState:
        ...

    @abstractmethod
    async def query_f_number(self) -> str | None:
        """Current iris F-number (e.g. "F9.8", "CLOSE") -- callable
        separately from `get_state()` so a fader drag can refresh it live
        without querying the full camera status on every tick."""
        ...

    @abstractmethod
    async def query_iris(self) -> tuple[float | None, bool | None]:
        """Current iris position (0.0-1.0) + auto-iris mode, in one query --
        callable separately from `get_state()`. The camera silently ignores
        iris-set commands while auto-iris is active, so callers re-query
        the real position afterward instead of trusting the target value."""
        ...

    @abstractmethod
    def subscribe(self, callback: Callable[[dict], None]) -> None:
        ...
