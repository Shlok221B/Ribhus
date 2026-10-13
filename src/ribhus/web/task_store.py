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


def _now() -> str:
    return datetime.now(UTC).isoformat()


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
    ts: str
    event: str
    data: dict[str, Any]

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
            events = [
                TaskEvent(
                    ts=str(e.get("ts", "")),
                    event=str(e.get("event", "")),
                    data=dict(e.get("data") or {}),
                )
                for e in (item.get("events") or [])
                if isinstance(e, dict)
            ]
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
            )

    def _save(self) -> None:
        rows = [t.to_dict() for t in sorted(
            self._tasks.values(), key=lambda t: t.created_at, reverse=True
        )[:200]]
        self.path.write_text(
            json.dumps(rows, indent=2, default=str),
            encoding="utf-8",
        )

    def create(self, prompt: str) -> TaskRecord:
        with self._lock:
            task = TaskRecord(
                id=uuid.uuid4().hex[:12],
                prompt=prompt.strip(),
                status="queued",
                created_at=_now(),
                updated_at=_now(),
            )
            self._tasks[task.id] = task
            self._save()
            return task

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

    def add_event(self, task_id: str, event: str, data: dict[str, Any] | None = None) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            task.events.append(
                TaskEvent(ts=_now(), event=event, data=dict(data or {}))
            )
            # Cap event list
            if len(task.events) > 200:
                task.events = task.events[-200:]
            task.updated_at = _now()
            self._save()

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
