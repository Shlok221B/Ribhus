from __future__ import annotations

import shutil
from pathlib import Path

from ribhus.skills.loader import load_skill
from ribhus.skills.models import Skill


SKILL_MD_TEMPLATE = """# {title}

## Goal
Describe what this skill helps the agent accomplish.

## Workflow
1. Clarify the user goal.
2. Use tools (search, browser, http) as needed.
3. Produce a clear final answer with sources.

## Constraints
- Only use legally accessible public information.
- Cite sources with URLs.
- Prefer English; support Hindi / Hinglish when the user writes in those.
"""


CONFIG_TEMPLATE = """name: {name}
version: 0.1.0
description: "{description}"
author: local
triggers:
  - {name}
languages:
  - en
permissions:
  - web
  - browser
"""


def skill_search_dirs(workspace: Path) -> list[Path]:
    bundled = Path(__file__).resolve().parent / "bundled"
    dirs = [workspace / "skills", workspace / ".ribhus" / "skills"]
    if bundled.exists():
        dirs.insert(0, bundled)
    return dirs


def install_skill(source: Path | str, *, workspace: Path) -> Skill:
    """Install a skill from a directory path or known name into .ribhus/skills."""
    dest_root = workspace / ".ribhus" / "skills"
    dest_root.mkdir(parents=True, exist_ok=True)

    if isinstance(source, str) and not Path(source).exists():
        skill = None
        for root in skill_search_dirs(workspace):
            candidate = root / source
            if candidate.is_dir() and (candidate / "config.yaml").exists():
                skill = load_skill(candidate)
                source_path = candidate
                break
        if skill is None:
            raise FileNotFoundError(
                f"Skill '{source}' not found. Try a path or a bundled skill name."
            )
    else:
        source_path = Path(source).resolve()
        skill = load_skill(source_path)

    dest = dest_root / skill.name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source_path, dest)
    return load_skill(dest)


def remove_skill(name: str, *, workspace: Path) -> None:
    dest = workspace / ".ribhus" / "skills" / name
    if not dest.exists():
        raise FileNotFoundError(f"Installed skill not found: {name}")
    shutil.rmtree(dest)


def create_skill(
    name: str,
    *,
    workspace: Path,
    description: str = "Custom Ribhus skill",
) -> Path:
    safe = name.strip().lower().replace(" ", "-")
    if not safe:
        raise ValueError("Skill name is required")
    target = workspace / "skills" / safe
    if target.exists():
        raise FileExistsError(f"Skill already exists: {target}")
    target.mkdir(parents=True)
    (target / "config.yaml").write_text(
        CONFIG_TEMPLATE.format(name=safe, description=description.replace('"', "'")),
        encoding="utf-8",
    )
    (target / "skill.md").write_text(
        SKILL_MD_TEMPLATE.format(title=safe.replace("-", " ").title()),
        encoding="utf-8",
    )
    (target / "examples.md").write_text(
        f'User: "Help me with {safe}."\n',
        encoding="utf-8",
    )
    return target
