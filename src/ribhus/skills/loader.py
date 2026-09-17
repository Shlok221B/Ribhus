from __future__ import annotations

from pathlib import Path

import yaml

from ribhus.skills.models import Skill, SkillConfig


def load_skill(path: Path) -> Skill:
    """Load a skill directory containing config.yaml and skill.md."""
    path = path.resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"Skill path is not a directory: {path}")

    config_path = path / "config.yaml"
    skill_md = path / "skill.md"
    if not config_path.exists():
        raise FileNotFoundError(f"Missing config.yaml in {path}")
    if not skill_md.exists():
        raise FileNotFoundError(f"Missing skill.md in {path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"config.yaml must be a mapping: {config_path}")
    if "name" not in raw:
        raw["name"] = path.name

    config = SkillConfig.model_validate(raw)
    instructions = skill_md.read_text(encoding="utf-8")
    examples = ""
    examples_md = path / "examples.md"
    if examples_md.exists():
        examples = examples_md.read_text(encoding="utf-8")

    return Skill(config=config, instructions=instructions, path=path, examples=examples)


def discover_skills(directories: list[Path]) -> list[Skill]:
    """Load all valid skill dirs from the given roots (later roots override names)."""
    by_name: dict[str, Skill] = {}
    for root in directories:
        if not root.exists() or not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            if not (child / "config.yaml").exists() or not (child / "skill.md").exists():
                continue
            try:
                skill = load_skill(child)
            except Exception:  # noqa: BLE001 — skip broken skills at discovery
                continue
            by_name[skill.name] = skill
    return list(by_name.values())
