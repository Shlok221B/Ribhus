from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ribhus.web.auth import AuthDep
from ribhus.web.runner import run_task
from ribhus.web.task_store import TaskStore

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _store(request: Request) -> TaskStore:
    return request.app.state.task_store


class CreateTaskBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)


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
    store = _store(request)
    task = store.create(body.prompt)
    asyncio.create_task(run_task(store, task.id))
    return task.to_dict()


@router.get("/{task_id}")
def get_task(task_id: str, request: Request, _: AuthDep) -> dict[str, Any]:
    task = _store(request).get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()


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
