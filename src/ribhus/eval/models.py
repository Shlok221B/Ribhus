from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

Status = Literal["pass", "fail", "skip"]
RunFn = Callable[[], Awaitable[None] | None]


class EvalSkip(Exception):
    """Case cannot run in this environment (missing extra, fixture, etc.)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    feature: str
    title: str
    fn: RunFn


@dataclass(frozen=True)
class EvalResult:
    case: EvalCase
    status: Status
    detail: str = ""
    duration_ms: float = 0.0
