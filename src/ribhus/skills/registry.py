from __future__ import annotations

from pathlib import Path

from ribhus.skills.loader import discover_skills, load_skill
from ribhus.skills.models import Skill


class SkillRegistry:
    def __init__(self, skills: list[Skill] | None = None) -> None:
        self._skills: dict[str, Skill] = {}
        for skill in skills or []:
            self.register(skill)

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def list(self) -> list[Skill]:
        return [self._skills[k] for k in sorted(self._skills)]

    def names(self) -> list[str]:
        return sorted(self._skills)

    def match(self, prompt: str) -> list[Skill]:
        return [skill for skill in self.list() if skill.matches(prompt)]

    def prompt_addon(self, prompt: str) -> str:
        matched = self.match(prompt)
        if not matched:
            # Still advertise available skills so the model can choose workflows.
            if not self._skills:
                return ""
            catalog = "\n".join(
                f"- {s.name}: {s.config.description}" for s in self.list()
            )
            return (
                "\n\n## Available skills\n"
                f"{catalog}\n"
                "If the user request matches a skill, follow that skill's workflow "
                "even if it was not auto-selected."
            )

        blocks = [skill.render() for skill in matched]
        names = ", ".join(s.name for s in matched)
        return (
            f"\n\n## Active skills ({names})\n"
            "Follow these skill instructions carefully for this request.\n\n"
            + "\n\n".join(blocks)
        )

    @classmethod
    def from_directories(cls, directories: list[Path]) -> SkillRegistry:
        return cls(discover_skills(directories))

    @classmethod
    def load_default(cls, workspace: Path) -> SkillRegistry:
        dirs = [
            workspace / "skills",
            workspace / ".ribhus" / "skills",
        ]
        # Packaged bundled skills (if present inside the install).
        bundled = Path(__file__).resolve().parent / "bundled"
        if bundled.exists():
            dirs.insert(0, bundled)
        return cls.from_directories(dirs)


def load_named_skill(name: str, search_dirs: list[Path]) -> Skill:
    for root in search_dirs:
        candidate = root / name
        if candidate.is_dir():
            return load_skill(candidate)
    raise FileNotFoundError(f"Skill '{name}' not found in {[str(d) for d in search_dirs]}")
