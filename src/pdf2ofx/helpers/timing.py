from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class Timer:
    start: float | None = None
    end: float | None = None

    def __enter__(self) -> "Timer":
        self.start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.end = time.perf_counter()

    @property
    def elapsed(self) -> float:
        if self.start is None:
            return 0.0
        if self.end is None:
            return time.perf_counter() - self.start
        return self.end - self.start
