from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

MemoryKind = Literal["short_term", "episodic", "semantic"]
KINDS: tuple[str, ...] = ("short_term", "episodic", "semantic")


class MemoryRecord(BaseModel):
    id: str
    kind: MemoryKind
    key: str | None = None
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    disabled: bool = False
    created_at: str
    updated_at: str

    def preview(self, limit: int = 80) -> str:
        text = " ".join(self.content.split())
        if len(text) <= limit:
            return text
        return text[: limit - 1] + "…"
