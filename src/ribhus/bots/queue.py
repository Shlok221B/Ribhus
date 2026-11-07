"""Per-bot serial work queues — different bots can run in parallel."""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

JobKind = Literal["user", "group", "handoff"]


@dataclass
class BotJob:
    kind: JobKind
    chat_id: str
    bot_id: str
    prompt: str
    task_id: str | None = None
    message_id: str | None = None
    # Handoff metadata
    from_bot_id: str | None = None
    from_chat_id: str | None = None
    priority: Literal["action", "fyi"] = "action"
    hop: int = 0
    # Group scheduling
    group_round: int = 0
    speak_or_pass: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


JobHandler = Callable[[BotJob], Awaitable[None]]


class BotQueueManager:
    """One FIFO queue per bot; workers run concurrently across bots."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._queues: dict[str, deque[BotJob]] = {}
        self._busy: set[str] = set()
        self._handler: JobHandler | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def set_handler(self, handler: JobHandler) -> None:
        self._handler = handler

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def enqueue(self, job: BotJob) -> None:
        with self._lock:
            q = self._queues.setdefault(job.bot_id, deque())
            # User messages jump ahead of fyi/handoff backlog except current work.
            if job.kind == "user":
                q.appendleft(job)
            else:
                q.append(job)
        self._kick(job.bot_id)

    def pending(self, bot_id: str) -> int:
        with self._lock:
            return len(self._queues.get(bot_id, ()))

    def is_busy(self, bot_id: str) -> bool:
        with self._lock:
            return bot_id in self._busy

    def _running_loop(self) -> asyncio.AbstractEventLoop | None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = self._loop
            if loop is None or loop.is_closed():
                return None
            return loop
        if self._loop is None or self._loop.is_closed() or self._loop is not loop:
            self._loop = loop
        return loop

    def _kick(self, bot_id: str) -> None:
        loop = self._running_loop()
        if loop is None:
            return
        with self._lock:
            if bot_id in self._busy:
                return
            q = self._queues.get(bot_id)
            if not q:
                return
            self._busy.add(bot_id)
        try:
            task = loop.create_task(self._drain(bot_id))
        except RuntimeError:
            with self._lock:
                self._busy.discard(bot_id)
            return
        self._tasks[bot_id] = task

    async def _drain(self, bot_id: str) -> None:
        handler = self._handler
        try:
            while True:
                with self._lock:
                    q = self._queues.get(bot_id)
                    if not q:
                        break
                    job = q.popleft()
                if handler is None:
                    continue
                try:
                    await handler(job)
                except Exception:  # noqa: BLE001 — isolate job failures
                    # Handler should log; keep draining.
                    pass
        finally:
            with self._lock:
                self._busy.discard(bot_id)
                self._tasks.pop(bot_id, None)
                has_more = bool(self._queues.get(bot_id))
            if has_more:
                self._kick(bot_id)
