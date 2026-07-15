from __future__ import annotations

MC_NOTE_ON = 0x7F


class MackieControlProtocol:
    def pitchbend_to_normalized(self, value: int) -> float:
        return max(0.0, min(1.0, value / 16383.0))

    def normalized_to_pitchbend(self, value: float) -> int:
        return int(max(0, min(16383, round(value * 16383))))
