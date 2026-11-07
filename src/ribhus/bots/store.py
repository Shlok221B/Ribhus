"""Persist the bot roster under .ribhus/bots.json."""

from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

BotStatus = Literal["idle", "working", "waiting"]

BOT_COLORS: tuple[str, ...] = (
    "copper",
    "blue",
    "gold",
    "verdigris",
    "rose",
    "info",
)

_DEFAULT_JOB = (
    "You are the primary Ribhus agent. Get things done with the available tools. "
    "Ask before consequential external actions. Prefer clear, sourced answers."
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _slug_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class BotRecord:
    id: str
    name: str
    label: str = ""
    color: str = "copper"
    job: str = ""
    is_primary: bool = False
    status: BotStatus = "idle"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def job_prompt_addon(self) -> str:
        text = (self.job or "").strip()
        if not text:
            return ""
        return (
            f"\n\n## Your role ({self.name})\n"
            f"{text}\n"
            "Stay in this role. Use message_bot to hand work to another bot when "
            "a specialist should own the next step.\n"
        )


class BotStore:
    """JSON-backed roster of durable bots."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._bots: dict[str, BotRecord] = {}
        self._load()
        if not self._bots:
            self._seed_primary()

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
            status = item.get("status", "idle")
            if status not in {"idle", "working", "waiting"}:
                status = "idle"
            # Don't revive mid-flight after restart.
            if status in {"working", "waiting"}:
                status = "idle"
            color = str(item.get("color") or "copper")
            if color not in BOT_COLORS:
                color = "copper"
            bot = BotRecord(
                id=str(item["id"]),
                name=str(item.get("name") or "Bot").strip() or "Bot",
                label=str(item.get("label") or ""),
                color=color,
                job=str(item.get("job") or ""),
                is_primary=bool(item.get("is_primary")),
                status=status,  # type: ignore[arg-type]
                created_at=str(item.get("created_at") or _now()),
                updated_at=str(item.get("updated_at") or _now()),
            )
            self._bots[bot.id] = bot
        self._ensure_one_primary()

    def _save(self) -> None:
        rows = [
            b.to_dict()
            for b in sorted(self._bots.values(), key=lambda b: b.created_at)
        ]
        self.path.write_text(
            json.dumps(rows, indent=2, default=str),
            encoding="utf-8",
        )

    def _seed_primary(self) -> None:
        bot = BotRecord(
            id=_slug_id(),
            name="Ribhus",
            label="Primary",
            color="copper",
            job=_DEFAULT_JOB,
            is_primary=True,
            status="idle",
        )
        self._bots[bot.id] = bot
        self._save()

    def _ensure_one_primary(self) -> None:
        primaries = [b for b in self._bots.values() if b.is_primary]
        if not self._bots:
            return
        if len(primaries) == 1:
            return
        if not primaries:
            first = sorted(self._bots.values(), key=lambda b: b.created_at)[0]
            first.is_primary = True
            first.updated_at = _now()
            self._save()
            return
        keep = sorted(primaries, key=lambda b: b.created_at)[0]
        for bot in primaries:
            bot.is_primary = bot.id == keep.id
        self._save()

    def list(self) -> list[BotRecord]:
        with self._lock:
            return sorted(
                self._bots.values(),
                key=lambda b: (0 if b.is_primary else 1, b.name.lower()),
            )

    def get(self, bot_id: str) -> BotRecord | None:
        with self._lock:
            return self._bots.get(bot_id)

    def get_by_name(self, name: str) -> BotRecord | None:
        needle = name.strip().lower()
        if not needle:
            return None
        with self._lock:
            for bot in self._bots.values():
                if bot.name.lower() == needle:
                    return bot
            # Allow @Name mentions without spaces mismatch
            compact = re.sub(r"\s+", "", needle)
            for bot in self._bots.values():
                if re.sub(r"\s+", "", bot.name.lower()) == compact:
                    return bot
        return None

    def primary(self) -> BotRecord:
        with self._lock:
            for bot in self._bots.values():
                if bot.is_primary:
                    return bot
            if not self._bots:
                self._seed_primary()
            return next(iter(self._bots.values()))

    def create(
        self,
        *,
        name: str,
        job: str = "",
        label: str = "",
        color: str = "copper",
        make_primary: bool = False,
    ) -> BotRecord:
        text = name.strip()
        if not text:
            raise ValueError("name is required")
        if self.get_by_name(text) is not None:
            raise ValueError(f"A bot named {text!r} already exists")
        if color not in BOT_COLORS:
            color = "copper"
        with self._lock:
            bot = BotRecord(
                id=_slug_id(),
                name=text,
                label=label.strip(),
                color=color,
                job=job.strip(),
                is_primary=False,
                status="idle",
            )
            self._bots[bot.id] = bot
            if make_primary or len(self._bots) == 1:
                self._set_primary_locked(bot.id)
            self._save()
            return bot

    def update(self, bot_id: str, **fields: Any) -> BotRecord | None:
        with self._lock:
            bot = self._bots.get(bot_id)
            if bot is None:
                return None
            if "name" in fields and fields["name"] is not None:
                new_name = str(fields["name"]).strip()
                if not new_name:
                    raise ValueError("name is required")
                other = self.get_by_name(new_name)
                if other is not None and other.id != bot_id:
                    raise ValueError(f"A bot named {new_name!r} already exists")
                bot.name = new_name
            if "label" in fields and fields["label"] is not None:
                bot.label = str(fields["label"]).strip()
            if "job" in fields and fields["job"] is not None:
                bot.job = str(fields["job"]).strip()
            if "color" in fields and fields["color"] is not None:
                color = str(fields["color"])
                if color in BOT_COLORS:
                    bot.color = color
            if "status" in fields and fields["status"] in {
                "idle",
                "working",
                "waiting",
            }:
                bot.status = fields["status"]
            if fields.get("is_primary") is True:
                self._set_primary_locked(bot_id)
            bot.updated_at = _now()
            self._save()
            return bot

    def set_primary(self, bot_id: str) -> BotRecord | None:
        with self._lock:
            if bot_id not in self._bots:
                return None
            self._set_primary_locked(bot_id)
            self._save()
            return self._bots[bot_id]

    def _set_primary_locked(self, bot_id: str) -> None:
        for bot in self._bots.values():
            bot.is_primary = bot.id == bot_id
            bot.updated_at = _now()

    def set_status(self, bot_id: str, status: BotStatus) -> None:
        with self._lock:
            bot = self._bots.get(bot_id)
            if bot is None:
                return
            bot.status = status
            bot.updated_at = _now()
            self._save()

    def delete(self, bot_id: str) -> BotRecord | None:
        with self._lock:
            bot = self._bots.pop(bot_id, None)
            if bot is None:
                return None
            if bot.is_primary and self._bots:
                first = sorted(self._bots.values(), key=lambda b: b.created_at)[0]
                first.is_primary = True
                first.updated_at = _now()
            self._save()
            return bot
