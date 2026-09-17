from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class SkillConfig(BaseModel):
    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    triggers: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=lambda: ["en"])
    permissions: list[str] = Field(default_factory=list)


class Skill(BaseModel):
    config: SkillConfig
    instructions: str
    path: Path
    examples: str = ""

    @property
    def name(self) -> str:
        return self.config.name

    def matches(self, prompt: str) -> bool:
        text = prompt.lower()
        if not self.config.triggers:
            return False
        return any(trigger.lower() in text for trigger in self.config.triggers)

    def render(self) -> str:
        parts = [
            f"### Skill: {self.config.name} (v{self.config.version})",
            self.config.description.strip(),
            "",
            self.instructions.strip(),
        ]
        if self.examples.strip():
            parts.extend(["", "#### Examples", self.examples.strip()])
        return "\n".join(parts).strip()
