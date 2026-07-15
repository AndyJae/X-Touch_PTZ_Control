from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FaderChannel:
    index: int
    name: str = ""


class Surface:
    def __init__(self) -> None:
        self.channels = [FaderChannel(index=i + 1) for i in range(8)]
