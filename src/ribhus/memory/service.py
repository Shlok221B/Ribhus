from __future__ import annotations

from pathlib import Path
from typing import Any

from ribhus.memory.models import KINDS, MemoryKind, MemoryRecord
from ribhus.memory.store import MemoryStore

MAX_PROMPT_CHARS = 3500
EPISODE_STORE_CHARS = 2000
SHORT_TERM_CHARS = 1200


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


class MemoryService:
    """User-owned memory: short-term, episodic tasks, semantic preferences."""

    def __init__(
        self,
        store: MemoryStore,
        *,
        env_enabled: bool = True,
    ) -> None:
        self.store = store
        self.env_enabled = env_enabled

    @classmethod
    def from_path(cls, path: Path, *, env_enabled: bool = True) -> MemoryService:
        return cls(MemoryStore(path), env_enabled=env_enabled)

    @property
    def enabled(self) -> bool:
        if not self.env_enabled:
            return False
        return self.store.get_setting("enabled", "true").lower() in {"1", "true", "yes"}

    def set_enabled(self, enabled: bool) -> None:
        self.store.set_setting("enabled", "true" if enabled else "false")

    def close(self) -> None:
        self.store.close()

    def add(
        self,
        content: str,
        *,
        kind: MemoryKind = "semantic",
        key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord:
        text = content.strip()
        if not text:
            raise ValueError("Memory content is required")
        if kind == "semantic" and key:
            return self.store.upsert_by_key(kind, key, text, metadata=metadata)
        if kind == "short_term":
            return self.store.upsert_by_key(
                "short_term", key or "last_turn", text, metadata=metadata
            )
        return self.store.insert(kind, text, key=key, metadata=metadata)

    def remember_fact(self, fact: str, *, key: str | None = None) -> MemoryRecord:
        return self.add(fact, kind="semantic", key=key)

    def set_short_term(self, prompt: str, answer: str) -> MemoryRecord | None:
        if not self.enabled:
            return None
        body = _clip(f"User: {prompt.strip()}\nRibhus: {answer.strip()}", SHORT_TERM_CHARS)
        return self.add(body, kind="short_term", key="last_turn")

    def record_episode(
        self,
        prompt: str,
        outcome: str,
        *,
        skills: list[str] | None = None,
        tools: list[str] | None = None,
    ) -> MemoryRecord | None:
        if not self.enabled:
            return None
        lines = [
            f"Task: {_clip(prompt, 400)}",
            f"Outcome: {_clip(outcome, 800)}",
        ]
        if skills:
            lines.append("Skills: " + ", ".join(skills))
        if tools:
            lines.append("Tools: " + ", ".join(dict.fromkeys(tools)))
        body = _clip("\n".join(lines), EPISODE_STORE_CHARS)
        return self.store.insert(
            "episodic",
            body,
            metadata={"skills": skills or [], "tools": tools or []},
        )

    def get(self, memory_id: str) -> MemoryRecord:
        record = self.store.get(memory_id)
        if record is None:
            raise FileNotFoundError(f"Memory not found: {memory_id}")
        return record

    def list(
        self,
        *,
        kind: MemoryKind | None = None,
        include_disabled: bool = False,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        if kind is not None and kind not in KINDS:
            raise ValueError(f"Unknown kind: {kind}. Use one of {', '.join(KINDS)}")
        return self.store.list(
            kind=kind, include_disabled=include_disabled, limit=limit
        )

    def search(self, query: str) -> list[MemoryRecord]:
        if not self.enabled:
            return []
        return self.store.search(query)

    def edit(self, memory_id: str, content: str) -> MemoryRecord:
        text = content.strip()
        if not text:
            raise ValueError("Memory content is required")
        return self.store.update(memory_id, content=text)

    def delete(self, memory_id: str) -> None:
        self.store.delete(memory_id)

    def disable(self, memory_id: str) -> MemoryRecord:
        return self.store.update(memory_id, disabled=True)

    def enable(self, memory_id: str) -> MemoryRecord:
        return self.store.update(memory_id, disabled=False)

    def export(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "env_enabled": self.env_enabled,
            "memories": self.store.export_all(),
        }

    def prompt_addon(self) -> str:
        """Compact context injected into the system prompt. Empty if disabled."""
        if not self.enabled:
            return ""
        parts: list[str] = []
        semantic = self.store.list(kind="semantic", limit=20)
        if semantic:
            lines = [f"- [{r.id}] { _clip(r.content, 240)}" for r in semantic]
            parts.append("### User preferences (semantic)\n" + "\n".join(lines))
        short = self.store.list(kind="short_term", limit=1)
        if short:
            parts.append("### Last turn (short-term)\n" + _clip(short[0].content, 500))
        episodic = self.store.list(kind="episodic", limit=5)
        if episodic:
            lines = [f"- [{r.id}] {_clip(r.content, 220)}" for r in episodic]
            parts.append("### Recent tasks (episodic)\n" + "\n".join(lines))
        if not parts:
            return ""
        body = "\n\n".join(parts)
        body = _clip(body, MAX_PROMPT_CHARS)
        return (
            "\n\n## Memory\n"
            "Use these saved facts when relevant. Do not invent extra memories. "
            "Call memory_remember for durable preferences the user states. "
            "The user can view, edit, delete, export, or disable memory via "
            "`ribhus memory`.\n\n"
            f"{body}"
        )
