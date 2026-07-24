from __future__ import annotations


class MackieControlProtocol:
    def pitchbend_to_normalized(self, value: int) -> float:
        return max(0.0, min(1.0, value / 16383.0))

    def normalized_to_pitchbend(self, value: float) -> int:
        return int(max(0, min(16383, round(value * 16383))))

    def encoder_cc_to_delta(self, raw_value: int) -> int:
        """CC 16-23 relative mode: value 1-7 = +, 65-71 = -."""
        if raw_value >= 64:
            return -(raw_value - 64)
        return raw_value
