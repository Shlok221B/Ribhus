"""Persist and track dashboard agent tasks."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

TaskStatus = Literal[
    "queued",
    "running",
    "awaiting_approval",
    "completed",
    "failed",
    "cancelled",
]

# Canonical turn-log event types (Epic 1A). Extra names (thinking, plan, …) allowed.
TurnEventType = Literal[
    "turn.started",
    "tool.started",
    "tool.finished",
    "approval.requested",
    "approval.resolved",
    "handoff.sent",
    "turn.completed",
    "turn.failed",
    "turn.cancelled",
]

_EVENT_ALIASES: dict[str, str] = {
    "started": "turn.started",
    "done": "turn.completed",
    "error": "turn.failed",
    "cancelled": "turn.cancelled",
    "tool_start": "tool.started",
    "tool_end": "tool.finished",
    "approval_requested": "approval.requested",
    "approval_resolved": "approval.resolved",
    "approval_edited": "approval.resolved",
    "handoff": "handoff.sent",
    "handoff_sent": "handoff.sent",
}

_BUSY: frozenset[str] = frozenset({"queued", "running", "awaiting_approval"})


class TaskBusyError(Exception):
    """Follow-up rejected because the task is still running."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def normalize_event_type(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return "unknown"
    return _EVENT_ALIASES.get(text, text)


@dataclass
class PendingApproval:
    id: str
    tool: str
    risk: str
    arguments: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskEvent:
    event_id: str
    seq: int
    ts: str
    event_type: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        # Canonical fields + legacy aliases for existing UI / maps helpers.
        return {
            "event_id": self.event_id,
            "seq": self.seq,
            "ts": self.ts,
            "event_type": self.event_type,
            "payload": self.payload,
            "event": self.event_type,
            "data": self.payload,
        }


def _event_from_dict(raw: dict[str, Any], *, fallback_seq: int) -> TaskEvent:
    event_type = normalize_event_type(
        str(raw.get("event_type") or raw.get("event") or "")
    )
    if "payload" in raw and isinstance(raw.get("payload"), dict):
        payload = dict(raw["payload"])
    else:
        payload = dict(raw.get("data") or {})
    seq_raw = raw.get("seq")
    try:
        seq = int(seq_raw) if seq_raw is not None else fallback_seq
    except (TypeError, ValueError):
        seq = fallback_seq
    event_id = str(raw.get("event_id") or uuid.uuid4().hex[:12])
    ts = str(raw.get("ts") or _now())
    return TaskEvent(
        event_id=event_id,
        seq=seq,
        ts=ts,
        event_type=event_type,
        payload=payload,
    )


@dataclass
class TaskTurn:
    role: Literal["user", "assistant"]
    content: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskRecord:
    id: str
    prompt: str
    status: TaskStatus
    created_at: str
    updated_at: str
    result: str | None = None
    error: str | None = None
    events: list[TaskEvent] = field(default_factory=list)
    pending_approval: PendingApproval | None = None
    skills: list[str] = field(default_factory=list)
    turns: list[TaskTurn] = field(default_factory=list)
    chat_id: str | None = None
    bot_id: str | None = None

    def current_prompt_and_history(self) -> tuple[str, list[dict[str, str]]]:
        """Latest user message, plus earlier turns for the agent."""
        turns = list(self.turns)
        if not turns:
            return self.prompt, []
        if turns[-1].role == "user":
            prompt = turns[-1].content
            prior = turns[:-1]
        else:
            prompt = self.prompt
            prior = turns
        history = [{"role": turn.role, "content": turn.content} for turn in prior]
        return prompt, history

    def to_dict(self) -> dict[str, Any]:
        from ribhus.tools.location import maps_places_for_task

        events = [e.to_dict() for e in self.events]
        return {
            "id": self.id,
            "prompt": self.prompt,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result,
            "error": self.error,
            "events": events,
            "pending_approval": (
                self.pending_approval.to_dict() if self.pending_approval else None
            ),
            "skills": list(self.skills),
            "turns": [turn.to_dict() for turn in self.turns],
            "chat_id": self.chat_id,
            "bot_id": self.bot_id,
            "maps_places": maps_places_for_task(
                prompt=self.prompt,
                result=self.result,
                events=events,
            ),
        }


class TaskStore:
    """JSON-backed task list with in-memory approval waiters."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._tasks: dict[str, TaskRecord] = {}
        self._approval_waiters: dict[str, dict[str, Any]] = {}
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
            events: list[TaskEvent] = []
            for idx, e in enumerate(item.get("events") or [], start=1):
                if isinstance(e, dict):
                    events.append(_event_from_dict(e, fallback_seq=idx))
            pending = None
            pa = item.get("pending_approval")
            if isinstance(pa, dict) and pa.get("id"):
                pending = PendingApproval(
                    id=str(pa["id"]),
                    tool=str(pa.get("tool", "")),
                    risk=str(pa.get("risk", "")),
                    arguments=dict(pa.get("arguments") or {}),
                    created_at=str(pa.get("created_at", "")),
                )
            status = item.get("status", "completed")
            # Don't revive mid-flight states after process restart.
            if status in {"queued", "running", "awaiting_approval"}:
                status = "failed"
                item["error"] = item.get("error") or "Interrupted by dashboard restart"
                pending = None
            turns = [
                TaskTurn(
                    role=turn["role"],
                    content=str(turn.get("content") or ""),
                )
                for turn in (item.get("turns") or [])
                if isinstance(turn, dict) and turn.get("role") in {"user", "assistant"}
            ]
            self._tasks[str(item["id"])] = TaskRecord(
                id=str(item["id"]),
                prompt=str(item.get("prompt", "")),
                status=status,  # type: ignore[arg-type]
                created_at=str(item.get("created_at", _now())),
                updated_at=str(item.get("updated_at", _now())),
                result=item.get("result"),
                error=item.get("error"),
                events=events,
                pending_approval=pending,
                skills=list(item.get("skills") or []),
                turns=turns,
                chat_id=str(item["chat_id"]) if item.get("chat_id") else None,
                bot_id=str(item["bot_id"]) if item.get("bot_id") else None,
            )

    def _save(self) -> None:
        rows = [t.to_dict() for t in sorted(
            self._tasks.values(), key=lambda t: t.created_at, reverse=True
        )[:200]]
        self.path.write_text(
            json.dumps(rows, indent=2, default=str),
            encoding="utf-8",
        )

    def create(
        self,
        prompt: str,
        *,
        chat_id: str | None = None,
        bot_id: str | None = None,
    ) -> TaskRecord:
        with self._lock:
            text = prompt.strip()
            task = TaskRecord(
                id=uuid.uuid4().hex[:12],
                prompt=text,
                status="queued",
                created_at=_now(),
                updated_at=_now(),
                turns=[TaskTurn(role="user", content=text)],
                chat_id=chat_id,
                bot_id=bot_id,
            )
            self._tasks[task.id] = task
            self._save()
            return task

    def append_follow_up(self, task_id: str, prompt: str) -> TaskRecord:
        """Queue another user message on an existing task."""
        text = prompt.strip()
        if not text:
            raise ValueError("prompt is empty")
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(task_id)
            if task.status in _BUSY:
                raise TaskBusyError(task_id)
            if not task.turns:
                task.turns.append(TaskTurn(role="user", content=task.prompt))
                if task.result:
                    task.turns.append(
                        TaskTurn(role="assistant", content=task.result)
                    )
            task.turns.append(TaskTurn(role="user", content=text))
            task.status = "queued"
            task.error = None
            task.pending_approval = None
            task.updated_at = _now()
            self._save()
            return task

    def add_assistant_turn(self, task_id: str, content: str) -> None:
        text = content.strip()
        if not text:
            return
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            if (
                task.turns
                and task.turns[-1].role == "assistant"
                and task.turns[-1].content == text
            ):
                return
            task.turns.append(TaskTurn(role="assistant", content=text))
            task.updated_at = _now()
            self._save()

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list(self, limit: int = 50) -> list[TaskRecord]:
        with self._lock:
            rows = sorted(
                self._tasks.values(), key=lambda t: t.created_at, reverse=True
            )
            return rows[:limit]

    def update(self, task_id: str, **fields: Any) -> TaskRecord | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            for key, value in fields.items():
                if hasattr(task, key):
                    setattr(task, key, value)
            task.updated_at = _now()
            self._save()
            return task

    def add_event(
        self,
        task_id: str,
        event: str,
        data: dict[str, Any] | None = None,
    ) -> TaskEvent | None:
        """Append a typed event. ``event`` may be canonical or a legacy alias."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            last_seq = task.events[-1].seq if task.events else 0
            row = TaskEvent(
                event_id=uuid.uuid4().hex[:12],
                seq=last_seq + 1,
                ts=_now(),
                event_type=normalize_event_type(event),
                payload=dict(data or {}),
            )
            task.events.append(row)
            if len(task.events) > 200:
                task.events = task.events[-200:]
            task.updated_at = _now()
            self._save()
            return row

    def list_events(
        self,
        task_id: str,
        *,
        after_seq: int = 0,
    ) -> list[TaskEvent]:
        """Return events with ``seq > after_seq`` (reconnect-friendly)."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(task_id)
            if after_seq <= 0:
                return list(task.events)
            return [e for e in task.events if e.seq > after_seq]

    def begin_approval(
        self,
        task_id: str,
        *,
        tool: str,
        risk: str,
        arguments: dict[str, Any],
    ) -> tuple[str, Any]:
        """Register a pending approval and return (approval_id, threading.Event)."""
        import threading as th

        approval_id = uuid.uuid4().hex[:10]
        event = th.Event()
        with self._lock:
            self._approval_waiters[approval_id] = {
                "event": event,
                "decision": None,
                "edited_text": None,
                "task_id": task_id,
            }
            task = self._tasks.get(task_id)
            if task is not None:
                task.status = "awaiting_approval"
                task.pending_approval = PendingApproval(
                    id=approval_id,
                    tool=tool,
                    risk=risk,
                    arguments=dict(arguments),
                    created_at=_now(),
                )
                task.updated_at = _now()
                self._save()
        return approval_id, event

    def resolve_approval(
        self,
        task_id: str,
        *,
        decision: Literal["approve", "deny", "edit"],
        edited_text: str | None = None,
    ) -> TaskRecord | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.pending_approval is None:
                return None
            approval_id = task.pending_approval.id
            waiter = self._approval_waiters.get(approval_id)
            if waiter is None:
                return None
            waiter["decision"] = decision
            waiter["edited_text"] = edited_text
            task.pending_approval = None
            task.status = "running"
            task.updated_at = _now()
            self._save()
            waiter["event"].set()
            return task

    def wait_approval_result(
        self, approval_id: str, timeout: float = 3600.0
    ) -> tuple[str, str | None]:
        """Block until resolved. Returns (decision, edited_text). Default deny on timeout."""
        with self._lock:
            waiter = self._approval_waiters.get(approval_id)
        if waiter is None:
            return "deny", None
        event: Any = waiter["event"]
        if not event.wait(timeout=timeout):
            with self._lock:
                waiter["decision"] = "deny"
                task_id = waiter.get("task_id")
                if task_id and task_id in self._tasks:
                    t = self._tasks[task_id]
                    t.pending_approval = None
                    if t.status == "awaiting_approval":
                        t.status = "running"
                    t.updated_at = _now()
                    self._save()
        with self._lock:
            decision = str(waiter.get("decision") or "deny")
            edited = waiter.get("edited_text")
            self._approval_waiters.pop(approval_id, None)
        return decision, edited if isinstance(edited, str) else None
