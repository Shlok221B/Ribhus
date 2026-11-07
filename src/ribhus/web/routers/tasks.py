from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ribhus.web.auth import AuthDep
from ribhus.web.runner import run_task
from ribhus.web.task_store import TaskBusyError, TaskStore

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _store(request: Request) -> TaskStore:
    return request.app.state.task_store


def _orch(request: Request):
    return getattr(request.app.state, "bot_orchestrator", None)


def _bots(request: Request):
    return getattr(request.app.state, "bot_store", None)


def _chats(request: Request):
    return getattr(request.app.state, "chat_store", None)


class CreateTaskBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    bot_id: str | None = None


class ApprovalBody(BaseModel):
    decision: Literal["approve", "deny", "edit"]
    edited_text: str | None = None


@router.get("")
def list_tasks(request: Request, _: AuthDep) -> list[dict[str, Any]]:
    return [t.to_dict() for t in _store(request).list()]


@router.post("")
async def create_task(
    request: Request, body: CreateTaskBody, _: AuthDep
) -> dict[str, Any]:
    """Start work on a bot (primary by default) via its direct chat."""
    orch = _orch(request)
    bots = _bots(request)
    chats = _chats(request)
    if orch is not None and bots is not None and chats is not None:
        bot = bots.get(body.bot_id) if body.bot_id else bots.primary()
        if bot is None:
            raise HTTPException(status_code=404, detail="Bot not found")
        chat = chats.direct_for_bot(bot.id, bot_name=bot.name)
        result = orch.enqueue_user_message(chat.id, body.prompt)
        task = result.get("task")
        if task is None:
            raise HTTPException(status_code=500, detail="Failed to queue task")
        # Include chat_id so the UI can navigate to the bot chat.
        task = dict(task)
        task["chat_id"] = chat.id
        task["bot_id"] = bot.id
        return task

    store = _store(request)
    task = store.create(body.prompt)
    asyncio.create_task(run_task(store, task.id))
    return task.to_dict()


@router.post("/{task_id}/follow-up")
async def follow_up_task(
    task_id: str, request: Request, body: CreateTaskBody, _: AuthDep
) -> dict[str, Any]:
    store = _store(request)
    task = store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    orch = _orch(request)
    chats = _chats(request)
    # Prefer continuing in the linked chat so the bot queue accepts the message.
    if orch is not None and chats is not None and task.chat_id:
        try:
            result = orch.enqueue_user_message(task.chat_id, body.prompt)
        except KeyError:
            raise HTTPException(status_code=404, detail="Chat not found") from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        follow = result.get("task") or task.to_dict()
        return follow

    try:
        task = store.append_follow_up(task_id, body.prompt)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found") from None
    except TaskBusyError:
        raise HTTPException(
            status_code=409,
            detail="Wait until this task finishes before sending another message",
        ) from None
    asyncio.create_task(run_task(store, task.id))
    return task.to_dict()


@router.get("/{task_id}")
def get_task(task_id: str, request: Request, _: AuthDep) -> dict[str, Any]:
    task = _store(request).get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()


@router.get("/{task_id}/events")
def list_task_events(
    task_id: str,
    request: Request,
    _: AuthDep,
    after_seq: int = 0,
) -> dict[str, Any]:
    """Incremental event poll. Returns events with seq > after_seq."""
    store = _store(request)
    try:
        events = store.list_events(task_id, after_seq=after_seq)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found") from None
    rows = [e.to_dict() for e in events]
    next_seq = rows[-1]["seq"] if rows else after_seq
    return {"task_id": task_id, "events": rows, "next_seq": next_seq}


@router.post("/{task_id}/approvals")
def resolve_approval(
    task_id: str, body: ApprovalBody, request: Request, _: AuthDep
) -> dict[str, Any]:
    task = _store(request).resolve_approval(
        task_id,
        decision=body.decision,
        edited_text=body.edited_text,
    )
    if task is None:
        raise HTTPException(status_code=404, detail="No pending approval")
    return task.to_dict()
