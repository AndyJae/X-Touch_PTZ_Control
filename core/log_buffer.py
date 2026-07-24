"""In-memory ring buffer backing the web UI's log view.

Attaches as a `logging.Handler` to the `ptz_control` logger (the parent of
every `ptz_control.*` logger in the project) and keeps its last 200 entries
in memory."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime

CAPACITY = 200


@dataclass(frozen=True)
class LogEntry:
    time: str
    level: str
    levelno: int
    message: str


class RingBufferHandler(logging.Handler):
    def __init__(self, capacity: int = CAPACITY) -> None:
        super().__init__()
        self._entries: deque[LogEntry] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        self._entries.append(
            LogEntry(
                time=datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
                level=record.levelname,
                levelno=record.levelno,
                message=record.getMessage(),
            )
        )

    def entries(self, min_level: int = logging.DEBUG) -> list[LogEntry]:
        return [entry for entry in self._entries if entry.levelno >= min_level]

    def clear(self) -> None:
        self._entries.clear()


LOG_BUFFER = RingBufferHandler()
LOG_BUFFER.setLevel(logging.DEBUG)
logging.getLogger("ptz_control").addHandler(LOG_BUFFER)
