from __future__ import annotations

import time


class RateLimiter:
    def __init__(self, max_hz: float = 15.0) -> None:
        self.max_hz = max_hz
        self._interval = 1.0 / max_hz
        self._last_sent = 0.0
        self._latest_value: float | None = None

    def should_send(self, value: float, *, final: bool = False) -> bool:
        now = time.monotonic()
        if final:
            self._last_sent = now
            return True
        if self._latest_value != value:
            self._latest_value = value
        if now - self._last_sent >= self._interval:
            self._last_sent = now
            return True
        return False
