from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    OK = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass
class Issue:
    severity: Severity
    reason: str
    fitids: list[str] = field(default_factory=list)
    count: int = 0
