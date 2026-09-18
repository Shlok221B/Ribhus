from __future__ import annotations

import random
from functools import lru_cache
from pathlib import Path

_STATUSES_PATH = Path(__file__).resolve().parent / "statuses.txt"
_FALLBACK = "pondering"
_recent: list[str] = []
_RECENT_WINDOW = 12


@lru_cache(maxsize=1)
def _lines() -> tuple[str, ...]:
    if not _STATUSES_PATH.exists():
        return (_FALLBACK,)
    out: list[str] = []
    for raw in _STATUSES_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return tuple(out) or (_FALLBACK,)


def random_status() -> str:
    """Pick a funny busy status, avoiding recent repeats."""
    choices = _lines()
    if len(choices) == 1:
        return choices[0]
    pool = [c for c in choices if c not in _recent] or list(choices)
    pick = random.choice(pool)
    _recent.append(pick)
    if len(_recent) > _RECENT_WINDOW:
        del _recent[0 : len(_recent) - _RECENT_WINDOW]
    return pick
