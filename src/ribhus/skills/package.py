from __future__ import annotations

from pathlib import Path

import yaml

REQUIRED_FILES = ("config.yaml", "skill.md", "README.md")
RECOMMENDED_FILES = ("examples.md", "tools.py")


class SkillPackageError(ValueError):
    """Skill directory is not a valid installable package."""


def validate_skill(path: Path, *, require_recommended: bool = False) -> list[str]:
    """Check a skill directory. Raises SkillPackageError if required files are missing.

    Returns warning strings for missing recommended files.
    """
    path = Path(path)
    if not path.is_dir():
        raise SkillPackageError(f"Skill path is not a directory: {path}")

    missing = [name for name in REQUIRED_FILES if not (path / name).exists()]
    if missing:
        raise SkillPackageError(
            f"Invalid skill package at {path}: missing {', '.join(missing)}. "
            "A skill needs config.yaml, skill.md, and README.md."
        )

    warnings: list[str] = []
    recommended_missing = [
        name for name in RECOMMENDED_FILES if not (path / name).exists()
    ]
    if recommended_missing:
        msg = f"Recommended files missing: {', '.join(recommended_missing)}"
        if require_recommended:
            raise SkillPackageError(f"{path}: {msg}")
        warnings.append(msg)
    if not (path / "tests").is_dir():
        msg = "Recommended: tests/ directory with at least one test"
        if require_recommended:
            raise SkillPackageError(f"{path}: {msg}")
        warnings.append(msg)

    raw = yaml.safe_load((path / "config.yaml").read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise SkillPackageError(f"config.yaml must be a mapping: {path / 'config.yaml'}")
    if not str(raw.get("name") or "").strip():
        raise SkillPackageError(f"config.yaml needs a name: {path / 'config.yaml'}")
    return warnings
