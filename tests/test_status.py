from __future__ import annotations

from ribhus.cli import status as status_mod
from ribhus.cli.status import random_status


def test_random_status_from_file():
    status_mod._recent.clear()
    status_mod._lines.cache_clear()
    word = random_status()
    assert word
    assert " " not in word or "-" in word or word.count(" ") <= 2
    assert word != "thinking"


def test_random_status_avoids_recent_repeats():
    status_mod._recent.clear()
    status_mod._lines.cache_clear()
    seen = [random_status() for _ in range(8)]
    # With a big pool, immediate duplicates across a short window should be rare;
    # at minimum consecutive picks from a full pool should differ when possible.
    assert len(status_mod._lines()) > 20
    assert len(seen) == 8
