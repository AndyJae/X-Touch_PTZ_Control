from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from core.state import CameraState


class CameraCommandError(Exception):
    """Kamera antwortet mit ER1/ER2/ER3 (bzw. eR1/2/3 bei ptz-Befehlen, §7.4)
    oder ist nach Timeout+1 Retry nicht erreichbar."""

    def __init__(self, message: str, *, command: str, response: str | None = None) -> None:
        super().__init__(message)
        self.command = command
        self.response = response


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
        """Rueckgabe (neuer dB-Wert oder `None` bei Auto, ist_auto) --
        Auto/AGC (Nutzerauftrag 2026-07-20) ist ein regulaerer dritter
        Gain-Zustand, kein Fehler."""
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
    def subscribe(self, callback: Callable[[dict], None]) -> None:
        ...
