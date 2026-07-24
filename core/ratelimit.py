from __future__ import annotations

import time


class RateLimiter:
    """Per-camera rate limiter: hysteresis delta filter + a max-`max_hz`
    token bucket. A `final=True` call always sends immediately, bypassing
    the bucket. Latest-wins: values dropped between sends are simply lost,
    there's no queue."""

    def __init__(self, max_hz: float = 15.0, *, hysteresis: float = 0.0) -> None:
        self._interval = 1.0 / max_hz
        self._hysteresis = hysteresis
        self._last_sent = float("-inf")
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
