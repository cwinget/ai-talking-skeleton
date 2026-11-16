"""In-memory ring buffer of recent log lines, for the admin UI's live log
view. A single module-level handler so any entry point (skeleton.server's
main(), or a test that builds Server() directly) picks up logging for free
once attached — see Server.__init__."""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from threading import Lock


@dataclass
class LogLine:
    id: int
    text: str


class RingBufferHandler(logging.Handler):
    def __init__(self, capacity: int = 500):
        super().__init__()
        self._lines: deque[LogLine] = deque(maxlen=capacity)
        self._next_id = 1
        self._lock = Lock()

    def emit(self, record: logging.LogRecord) -> None:
        text = self.format(record)
        with self._lock:
            line = LogLine(self._next_id, text)
            self._lines.append(line)
            self._next_id += 1

    def tail(self, after: int = 0, limit: int = 300) -> list[LogLine]:
        with self._lock:
            lines = [ln for ln in self._lines if ln.id > after]
        return lines[-limit:]


RING = RingBufferHandler()
# Its own formatter (independent of the console handler's): includes the
# level so the admin UI's log view can highlight WARNING/ERROR lines.
RING.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S"))


def install() -> None:
    root = logging.getLogger()
    if RING not in root.handlers:
        root.addHandler(RING)
