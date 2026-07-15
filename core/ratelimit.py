from __future__ import annotations

import time


class RateLimiter:
    """Rate-Limiter pro Kamera, Spec §8: Delta-Filter (Hysterese) + Token-Bucket
    (max. `max_hz`), Touch-Release/`final` sendet immer priorisiert am Bucket
    vorbei. Latest-wins ist implizit: verworfene Zwischenwerte gehen verloren,
    der Aufrufer haelt selbst keine Queue.
    """

    def __init__(self, max_hz: float = 15.0, *, hysteresis: float = 0.0) -> None:
        self.max_hz = max_hz
        self._interval = 1.0 / max_hz
        self._hysteresis = hysteresis
        self._last_sent = float("-inf")  # "noch nie gesendet", unabhaengig vom Clock-Epoch
        self._latest_value: float | None = None

    def should_send(self, value: float, *, final: bool = False) -> bool:
        now = time.monotonic()
        if final:
            self._latest_value = value
            self._last_sent = now
            return True
        if self._latest_value is not None and abs(value - self._latest_value) < self._hysteresis:
            return False
        if now - self._last_sent < self._interval:
            return False
        self._latest_value = value
        self._last_sent = now
        return True
