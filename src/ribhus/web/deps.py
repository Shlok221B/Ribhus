"""Shared dashboard runtime helpers."""

from __future__ import annotations

from pathlib import Path

from ribhus.config import Settings, get_settings


def settings() -> Settings:
    return get_settings()


def resolve_web_dist() -> Path | None:
    """Locate built SPA assets (repo web/dist preferred)."""
    here = Path(__file__).resolve()
    candidates = [
        Path.cwd() / "web" / "dist",
        here.parents[3] / "web" / "dist",  # repo root when installed from src
        here.parent / "static",
    ]
    for path in candidates:
        if (path / "index.html").is_file():
            return path
    return None


def resolve_web_root() -> Path:
    """Source web/ directory for npm build."""
    here = Path(__file__).resolve()
    candidates = [
        Path.cwd() / "web",
        here.parents[3] / "web",
    ]
    for path in candidates:
        if (path / "package.json").is_file():
            return path
    raise FileNotFoundError("Could not find Ribhus web/ package.json")
