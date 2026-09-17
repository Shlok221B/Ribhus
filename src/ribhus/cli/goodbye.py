from __future__ import annotations

import random
from functools import lru_cache
from pathlib import Path

_GOODBYES_PATH = Path(__file__).resolve().parent / "goodbyes.txt"
_FALLBACK = "Bye!"


@lru_cache(maxsize=1)
def _lines() -> tuple[str, ...]:
    if not _GOODBYES_PATH.exists():
        return (_FALLBACK,)
    out: list[str] = []
    for raw in _GOODBYES_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return tuple(out) or (_FALLBACK,)


def random_goodbye() -> str:
    """Pick a random line from goodbyes.txt."""
    return random.choice(_lines())
