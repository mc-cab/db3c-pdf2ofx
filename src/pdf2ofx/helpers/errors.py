from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Stage(str, Enum):
    PREFLIGHT = "PREFLIGHT"
    MINDEE = "MINDEE"
    NORMALIZE = "NORMALIZE"
    VALIDATE = "VALIDATE"
    EMIT = "EMIT"
    WRITE = "WRITE"


@dataclass
class StageError(Exception):
    stage: Stage
    message: str
    hint: str | None = None

    def __str__(self) -> str:
        if self.hint:
            return f"[{self.stage}] {self.message} ({self.hint})"
        return f"[{self.stage}] {self.message}"


def format_stage_error(err: StageError) -> str:
    if err.hint:
        return f"{err.message} — {err.hint}"
    return err.message
