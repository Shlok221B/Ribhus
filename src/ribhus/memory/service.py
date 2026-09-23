from __future__ import annotations

from pathlib import Path
from typing import Any

from ribhus.memory.extract import PINNED_KEYS, extract_prefs_from_text
from ribhus.memory.models import KINDS, MemoryKind, MemoryRecord
from ribhus.memory.store import MemoryStore

MAX_PROMPT_CHARS = 3500
EPISODE_STORE_CHARS = 1200
SHORT_TERM_CHARS = 1200
DEFAULT_EPISODE_KEEP = 80


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
        episode_keep: int = DEFAULT_EPISODE_KEEP,
    ) -> None:
        self.store = store
        self.env_enabled = env_enabled
        self.episode_keep = episode_keep
        self.last_injected: list[str] = []

    @classmethod
    def from_path(
        cls,
        path: Path,
        *,
        env_enabled: bool = True,
        episode_keep: int = DEFAULT_EPISODE_KEEP,
    ) -> MemoryService:
        return cls(
            MemoryStore(path),
            env_enabled=env_enabled,
            episode_keep=episode_keep,
        )

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

    def learn_whatsapp_style(self, messages: list[dict[str, Any]]) -> str | None:
        """Update global WhatsApp writing-style profile from outgoing messages.

        Returns the updated profile text, or None if nothing learned / memory off.
        """
        if not self.enabled:
            return None
        from ribhus.channels.whatsapp_web.style_profile import (
            WHATSAPP_STYLE_KEY,
            extract_outgoing_style,
            merge_style,
        )

        self_names = self._self_names_for_style()
        snapshot = extract_outgoing_style(messages, self_names=self_names)
        if snapshot is None:
            return None
        existing = ""
        try:
            rows = self.store.get_by_keys([WHATSAPP_STYLE_KEY])
            if rows:
                existing = rows[0].content
        except Exception:  # noqa: BLE001
            existing = ""
        merged = merge_style(existing, snapshot)
        self.remember_fact(merged, key=WHATSAPP_STYLE_KEY)
        return merged

    def _self_names_for_style(self) -> list[str]:
        """Names that may appear in WhatsApp data-pre-plain-text for your bubbles."""
        names: list[str] = []
        try:
            for row in self.store.get_by_keys(["name", "user_name", "display_name"]):
                text = (row.content or "").strip()
                # "Shlok" or "Name: Shlok" / "Prefer …"
                if ":" in text:
                    text = text.split(":")[-1].strip()
                if text and len(text) < 40:
                    names.append(text)
                    # First token only (e.g. Shlok from "Shlok Kumar")
                    first = text.split()[0]
                    if first and first.casefold() not in {n.casefold() for n in names}:
                        names.append(first)
        except Exception:  # noqa: BLE001
            pass
        return names

    def get_whatsapp_style(self) -> str | None:
        if not self.enabled:
            return None
        from ribhus.channels.whatsapp_web.style_profile import WHATSAPP_STYLE_KEY

        rows = self.store.get_by_keys([WHATSAPP_STYLE_KEY])
        if not rows:
            return None
        return rows[0].content

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
            f"Task: {_clip(prompt, 280)}",
            f"Outcome: {_clip(outcome, 500)}",
        ]
        if skills:
            lines.append("Skills: " + ", ".join(skills))
        if tools:
            lines.append("Tools: " + ", ".join(dict.fromkeys(tools)))
        body = _clip("\n".join(lines), EPISODE_STORE_CHARS)
        record = self.store.insert(
            "episodic",
            body,
            metadata={"skills": skills or [], "tools": tools or []},
        )
        self.prune_episodes()
        return record

    def prune_episodes(self, keep: int | None = None) -> int:
        return self.store.prune_kind("episodic", keep=keep if keep is not None else self.episode_keep)

    def extract_and_persist(self, *texts: str) -> list[str]:
        """Pull prefs from texts into semantic memory. Returns display labels."""
        if not self.enabled:
            return []
        labels: list[str] = []
        seen: set[str] = set()
        for text in texts:
            for pref in extract_prefs_from_text(text):
                if pref.key in seen:
                    continue
                seen.add(pref.key)
                self.remember_fact(pref.content, key=pref.key)
                labels.append(f"{pref.key} → {pref.content}")
        return labels

    def prepare_for_prompt(
        self,
        prompt: str,
        *,
        skill_names: list[str] | None = None,
    ) -> list[str]:
        """Extract prefs from the prompt; football skill may infer club."""
        labels = self.extract_and_persist(prompt)
        if self.enabled and skill_names and "football" in skill_names:
            from ribhus.memory.football import ensure_football_club

            club = ensure_football_club(self, prompt=prompt)
            if club and not any(x.startswith("football_club") for x in labels):
                labels.append(f"football_club → {club}")
        return labels

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

    def search(
        self,
        query: str,
        *,
        kind: MemoryKind | None = None,
        limit: int = 12,
    ) -> list[MemoryRecord]:
        if not self.enabled:
            return []
        return self.store.search(query, kind=kind, limit=limit)

    def edit(self, memory_id: str, content: str) -> MemoryRecord:
        text = content.strip()
        if not text:
            raise ValueError("Memory content is required")
        return self.store.update(memory_id, content=text)

    def delete(self, memory_id: str) -> None:
        self.store.delete(memory_id)

    def forget(self, target: str) -> str:
        """Delete by memory id or semantic key. Returns a short status string."""
        target = target.strip()
        if not target:
            raise ValueError("Memory id or key is required")
        if self.store.get(target) is not None:
            self.store.delete(target)
            return f"Deleted {target}"
        deleted = self.store.delete_by_key("semantic", target)
        if deleted:
            return f"Deleted {deleted} (key={target})"
        raise FileNotFoundError(f"Memory not found: {target}")

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

    def prompt_addon(self, query: str = "") -> str:
        """Compact, query-aware context for the system prompt."""
        self.last_injected = []
        if not self.enabled:
            return ""

        parts: list[str] = []
        used_ids: set[str] = set()

        pinned = self.store.get_by_keys(list(PINNED_KEYS))
        if pinned:
            lines = []
            for r in pinned:
                lines.append(f"- [{r.id}] ({r.key}) {_clip(r.content, 240)}")
                used_ids.add(r.id)
                self.last_injected.append(f"{r.key}: {_clip(r.content, 80)}")
            parts.append("### Pinned preferences\n" + "\n".join(lines))

        relevant: list[MemoryRecord] = []
        if query.strip():
            relevant = [
                r
                for r in self.store.search(query, limit=8)
                if r.id not in used_ids
            ]
            # Prefer semantic hits for prefs questions
            semantic_hits = [r for r in relevant if r.kind == "semantic"][:4]
            episodic_hits = [r for r in relevant if r.kind == "episodic"][:3]
            relevant = semantic_hits + episodic_hits

        if relevant:
            lines = []
            for r in relevant:
                label = f"{r.kind}" + (f"/{r.key}" if r.key else "")
                lines.append(f"- [{r.id}] ({label}) {_clip(r.content, 220)}")
                used_ids.add(r.id)
                self.last_injected.append(f"match:{_clip(r.content, 60)}")
            parts.append("### Relevant to this request\n" + "\n".join(lines))

        semantic = [
            r
            for r in self.store.list(kind="semantic", limit=20)
            if r.id not in used_ids
        ][:12]
        if semantic:
            lines = [f"- [{r.id}] {_clip(r.content, 200)}" for r in semantic]
            for r in semantic:
                used_ids.add(r.id)
            parts.append("### Other preferences\n" + "\n".join(lines))

        short = self.store.list(kind="short_term", limit=1)
        if short:
            parts.append("### Last turn (short-term)\n" + _clip(short[0].content, 500))
            self.last_injected.append("short_term: last turn")

        if not query.strip() or not any(r.kind == "episodic" for r in relevant):
            episodic = [
                r
                for r in self.store.list(kind="episodic", limit=5)
                if r.id not in used_ids
            ]
            if episodic:
                lines = [f"- [{r.id}] {_clip(r.content, 200)}" for r in episodic]
                parts.append("### Recent tasks (episodic)\n" + "\n".join(lines))
                self.last_injected.append(f"episodic: {len(episodic)} recent")

        if not parts:
            return ""
        body = _clip("\n\n".join(parts), MAX_PROMPT_CHARS)
        return (
            "\n\n## Memory\n"
            "Use these saved facts when relevant. Do not invent extra memories. "
            "Call memory_remember for durable preferences the user states. "
            "Call memory_forget when they ask to forget something. "
            "The user can view, edit, delete, export, or disable memory via "
            "`ribhus memory`.\n\n"
            f"{body}"
        )
