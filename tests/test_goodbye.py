from pathlib import Path

from ribhus.cli.goodbye import _lines, random_goodbye


def test_goodbyes_file_has_lines():
    path = Path(__file__).resolve().parents[1] / "src" / "ribhus" / "cli" / "goodbyes.txt"
    assert path.exists()
    lines = _lines()
    assert len(lines) >= 5
    assert all(not line.startswith("#") for line in lines)


def test_random_goodbye_from_file():
    lines = set(_lines())
    picks = {random_goodbye() for _ in range(40)}
    assert picks <= lines
    assert picks  # at least one
