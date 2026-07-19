"""In-Memory-Ringpuffer fuer die Web-UI-Log-Ansicht (Spec §10 Punkt 4:
"Log-Ansicht: letzte 200 Zeilen, Filter nach Level").

Haengt sich als `logging.Handler` an den `ptz_control`-Logger (Elternlogger
aller `ptz_control.*`-Logger im Projekt, siehe `main.py`/`core/application.py`/
`midi/fader.py`/`web/app.py`) und haelt dessen letzte 200 Eintraege im
Speicher vor -- unabhaengig davon, ob die App ueber `main.py` (mit
`logging.basicConfig`) oder direkt als `web.app.app` (z. B. in Tests) laeuft.
"""

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
