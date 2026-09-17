from __future__ import annotations

import shutil
from pathlib import Path

from ribhus.skills.loader import load_skill
from ribhus.skills.models import Skill
from ribhus.skills.package import SkillPackageError, validate_skill


SKILL_MD_TEMPLATE = """# {title}

## Goal
Describe what this skill helps the agent accomplish.

## Languages
- Default: English
- If the user writes in Hindi or Hinglish, reply in the same style

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

README_TEMPLATE = """# {title}

Ribhus skill. Install with:

```bash
ribhus skill install {name}
# or
ribhus skill install ./skills/{name}
```

## What it does

{description}

## Package layout

- `config.yaml` — name, version, triggers, permissions
- `skill.md` — workflow the agent must follow
- `examples.md` — sample prompts
- `tools.py` — optional notes (not auto-imported; skills are untrusted)
- `tests/` — package checks

See [docs/skills.md](../../docs/skills.md) for the contributor guide.
"""

TOOLS_PY_TEMPLATE = '''"""Optional skill extras.

Ribhus does **not** auto-import this file. Untrusted skills must not run
arbitrary Python. Document tools this skill expects the agent to use.
"""

# Names of core Ribhus tools this skill relies on.
SKILL_TOOLS = ["web_search", "browser", "http_request"]
'''

TEST_TEMPLATE = '''from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_package_files_exist():
    for name in ("config.yaml", "skill.md", "README.md"):
        assert (ROOT / name).exists(), name


def test_config_name():
    raw = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    assert raw["name"]
'''


def skill_search_dirs(workspace: Path) -> list[Path]:
    bundled = Path(__file__).resolve().parent / "bundled"
    dirs = [workspace / "skills", workspace / ".ribhus" / "skills"]
    if bundled.exists():
        dirs.insert(0, bundled)
    return dirs


def install_skill_with_warnings(
    source: Path | str, *, workspace: Path
) -> tuple[Skill, list[str]]:
    """Install a skill from a directory path or known name into .ribhus/skills."""
    dest_root = workspace / ".ribhus" / "skills"
    dest_root.mkdir(parents=True, exist_ok=True)

    if isinstance(source, str) and not Path(source).exists():
        source_path: Path | None = None
        for root in skill_search_dirs(workspace):
            candidate = root / source
            if candidate.is_dir() and (candidate / "config.yaml").exists():
                source_path = candidate
                break
        if source_path is None:
            raise FileNotFoundError(
                f"Skill '{source}' not found. Try a path or a bundled skill name."
            )
    else:
        source_path = Path(source).resolve()

    warnings = validate_skill(source_path)
    skill = load_skill(source_path)
    dest = dest_root / skill.name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source_path, dest)
    return load_skill(dest), warnings


def install_skill(source: Path | str, *, workspace: Path) -> Skill:
    skill, _warnings = install_skill_with_warnings(source, workspace=workspace)
    return skill


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
    title = safe.replace("-", " ").title()
    desc = description.replace('"', "'")
    (target / "config.yaml").write_text(
        CONFIG_TEMPLATE.format(name=safe, description=desc),
        encoding="utf-8",
    )
    (target / "skill.md").write_text(
        SKILL_MD_TEMPLATE.format(title=title),
        encoding="utf-8",
    )
    (target / "examples.md").write_text(
        f'User: "Help me with {safe}."\n',
        encoding="utf-8",
    )
    (target / "README.md").write_text(
        README_TEMPLATE.format(title=title, name=safe, description=desc),
        encoding="utf-8",
    )
    (target / "tools.py").write_text(TOOLS_PY_TEMPLATE, encoding="utf-8")
    tests_dir = target / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_skill.py").write_text(TEST_TEMPLATE, encoding="utf-8")
    validate_skill(target)
    return target


__all__ = [
    "SkillPackageError",
    "create_skill",
    "install_skill",
    "install_skill_with_warnings",
    "remove_skill",
    "skill_search_dirs",
    "validate_skill",
]
