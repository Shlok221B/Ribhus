"""Persist direct and group chats under .ribhus/chats.json."""

from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

ChatKind = Literal["direct", "group"]
MessageRole = Literal["user", "assistant", "system", "handoff", "bot"]

_MENTION_RE = re.compile(r"@([A-Za-z0-9][A-Za-z0-9 _-]{0,40})")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _slug_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class ChatMessage:
    id: str
    role: MessageRole
    content: str
    created_at: str = field(default_factory=_now)
    bot_id: str | None = None
    bot_name: str | None = None
    task_id: str | None = None
    handoff: dict[str, Any] | None = None
    mention_bot_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChatRecord:
    id: str
    kind: ChatKind
    title: str
    bot_ids: list[str]
    created_at: str
    updated_at: str
    messages: list[ChatMessage] = field(default_factory=list)
    active_task_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "bot_ids": list(self.bot_ids),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [m.to_dict() for m in self.messages],
            "active_task_id": self.active_task_id,
        }

    def history_for_bot(self, bot_id: str | None = None) -> list[dict[str, str]]:
        """OpenAI-style prior turns for an agent run (excluding the latest user)."""
        rows: list[dict[str, str]] = []
        for msg in self.messages:
            if msg.role == "user":
                rows.append({"role": "user", "content": msg.content})
            elif msg.role in {"assistant", "bot"}:
                name = msg.bot_name or "assistant"
                prefix = f"[{name}] " if self.kind == "group" else ""
                rows.append({"role": "assistant", "content": prefix + msg.content})
            elif msg.role == "handoff":
                rows.append(
                    {
                        "role": "user",
                        "content": f"(Handoff) {msg.content}",
                    }
                )
            elif msg.role == "system":
                rows.append({"role": "user", "content": f"(System) {msg.content}"})
        return rows


def parse_mentions(text: str, known_names: dict[str, str]) -> list[str]:
    """Return bot ids mentioned via @Name, preserving order and uniqueness.

    known_names maps lowercased name → bot_id.
    """
    found: list[str] = []
    seen: set[str] = set()
    for match in _MENTION_RE.finditer(text or ""):
        raw = match.group(1).strip().lower()
        # Try full match, then progressive token shrink for multi-word names.
        candidates = [raw]
        parts = raw.split()
        for i in range(len(parts), 0, -1):
            candidates.append(" ".join(parts[:i]))
        bot_id = None
        for cand in candidates:
            key = re.sub(r"\s+", " ", cand).strip()
            if key in known_names:
                bot_id = known_names[key]
                break
            compact = re.sub(r"\s+", "", key)
            for name, bid in known_names.items():
                if re.sub(r"\s+", "", name) == compact:
                    bot_id = bid
                    break
            if bot_id:
                break
        if bot_id and bot_id not in seen:
            seen.add(bot_id)
            found.append(bot_id)
    return found


class ChatStore:
    """JSON-backed chats (direct + group)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._chats: dict[str, ChatRecord] = {}
        self._direct_by_bot: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, list):
            return
        for item in raw:
            if not isinstance(item, dict) or "id" not in item:
                continue
            kind = item.get("kind", "direct")
            if kind not in {"direct", "group"}:
                kind = "direct"
            messages: list[ChatMessage] = []
            for m in item.get("messages") or []:
                if not isinstance(m, dict):
                    continue
                role = m.get("role", "user")
                if role not in {"user", "assistant", "system", "handoff", "bot"}:
                    continue
                messages.append(
                    ChatMessage(
                        id=str(m.get("id") or _slug_id()),
                        role=role,  # type: ignore[arg-type]
                        content=str(m.get("content") or ""),
                        created_at=str(m.get("created_at") or _now()),
                        bot_id=m.get("bot_id"),
                        bot_name=m.get("bot_name"),
                        task_id=m.get("task_id"),
                        handoff=dict(m["handoff"])
                        if isinstance(m.get("handoff"), dict)
                        else None,
                        mention_bot_ids=list(m.get("mention_bot_ids") or []),
                    )
                )
            chat = ChatRecord(
                id=str(item["id"]),
                kind=kind,  # type: ignore[arg-type]
                title=str(item.get("title") or ""),
                bot_ids=[str(b) for b in (item.get("bot_ids") or [])],
                created_at=str(item.get("created_at") or _now()),
                updated_at=str(item.get("updated_at") or _now()),
                messages=messages,
                active_task_id=item.get("active_task_id"),
            )
            self._chats[chat.id] = chat
            if chat.kind == "direct" and len(chat.bot_ids) == 1:
                self._direct_by_bot[chat.bot_ids[0]] = chat.id

    def _save(self) -> None:
        rows = [
            c.to_dict()
            for c in sorted(self._chats.values(), key=lambda c: c.updated_at, reverse=True)
        ][:300]
        self.path.write_text(
            json.dumps(rows, indent=2, default=str),
            encoding="utf-8",
        )

    def list(self, limit: int = 100) -> list[ChatRecord]:
        with self._lock:
            rows = sorted(
                self._chats.values(), key=lambda c: c.updated_at, reverse=True
            )
            return rows[:limit]

    def get(self, chat_id: str) -> ChatRecord | None:
        with self._lock:
            return self._chats.get(chat_id)

    def direct_for_bot(self, bot_id: str, *, bot_name: str = "") -> ChatRecord:
        """Get or create the direct chat for a bot."""
        with self._lock:
            existing_id = self._direct_by_bot.get(bot_id)
            if existing_id and existing_id in self._chats:
                return self._chats[existing_id]
            chat = ChatRecord(
                id=_slug_id(),
                kind="direct",
                title=bot_name or "Direct",
                bot_ids=[bot_id],
                created_at=_now(),
                updated_at=_now(),
            )
            self._chats[chat.id] = chat
            self._direct_by_bot[bot_id] = chat.id
            self._save()
            return chat

    def create_group(
        self,
        *,
        bot_ids: list[str],
        title: str = "",
        bot_names: dict[str, str] | None = None,
    ) -> ChatRecord:
        ids = list(dict.fromkeys(b for b in bot_ids if b))
        if len(ids) < 2:
            raise ValueError("A group needs at least 2 bots")
        if len(ids) > 6:
            raise ValueError("A group can have at most 6 bots")
        names = bot_names or {}
        label = title.strip() or ", ".join(names.get(b, b[:6]) for b in ids)
        with self._lock:
            chat = ChatRecord(
                id=_slug_id(),
                kind="group",
                title=label,
                bot_ids=ids,
                created_at=_now(),
                updated_at=_now(),
            )
            self._chats[chat.id] = chat
            self._save()
            return chat

    def update(
        self,
        chat_id: str,
        *,
        title: str | None = None,
        bot_ids: list[str] | None = None,
        active_task_id: str | None | object = ...,
    ) -> ChatRecord | None:
        with self._lock:
            chat = self._chats.get(chat_id)
            if chat is None:
                return None
            if title is not None:
                chat.title = title.strip() or chat.title
            if bot_ids is not None:
                ids = list(dict.fromkeys(b for b in bot_ids if b))
                if chat.kind == "group":
                    if len(ids) < 2 or len(ids) > 6:
                        raise ValueError("A group needs 2–6 bots")
                    chat.bot_ids = ids
            if active_task_id is not ...:
                chat.active_task_id = (
                    str(active_task_id) if active_task_id else None
                )
            chat.updated_at = _now()
            self._save()
            return chat

    def delete(self, chat_id: str) -> ChatRecord | None:
        with self._lock:
            chat = self._chats.pop(chat_id, None)
            if chat is None:
                return None
            if chat.kind == "direct" and chat.bot_ids:
                self._direct_by_bot.pop(chat.bot_ids[0], None)
            self._save()
            return chat

    def delete_for_bot(self, bot_id: str) -> list[str]:
        """Remove chats owned solely by this bot; drop bot from groups."""
        removed: list[str] = []
        with self._lock:
            to_delete: list[str] = []
            for chat in self._chats.values():
                if chat.kind == "direct" and bot_id in chat.bot_ids:
                    to_delete.append(chat.id)
                elif chat.kind == "group" and bot_id in chat.bot_ids:
                    chat.bot_ids = [b for b in chat.bot_ids if b != bot_id]
                    chat.updated_at = _now()
                    if len(chat.bot_ids) < 2:
                        to_delete.append(chat.id)
            for cid in to_delete:
                self._chats.pop(cid, None)
                removed.append(cid)
            self._direct_by_bot.pop(bot_id, None)
            self._save()
        return removed

    def append_message(
        self,
        chat_id: str,
        *,
        role: MessageRole,
        content: str,
        bot_id: str | None = None,
        bot_name: str | None = None,
        task_id: str | None = None,
        handoff: dict[str, Any] | None = None,
        mention_bot_ids: list[str] | None = None,
    ) -> ChatMessage | None:
        with self._lock:
            chat = self._chats.get(chat_id)
            if chat is None:
                return None
            msg = ChatMessage(
                id=_slug_id(),
                role=role,
                content=content,
                bot_id=bot_id,
                bot_name=bot_name,
                task_id=task_id,
                handoff=handoff,
                mention_bot_ids=list(mention_bot_ids or []),
            )
            chat.messages.append(msg)
            if len(chat.messages) > 500:
                chat.messages = chat.messages[-500:]
            if task_id:
                chat.active_task_id = task_id
            chat.updated_at = _now()
            self._save()
            return msg

    def set_message_task(self, chat_id: str, message_id: str, task_id: str) -> None:
        with self._lock:
            chat = self._chats.get(chat_id)
            if chat is None:
                return
            for msg in chat.messages:
                if msg.id == message_id:
                    msg.task_id = task_id
                    break
            chat.active_task_id = task_id
            chat.updated_at = _now()
            self._save()
