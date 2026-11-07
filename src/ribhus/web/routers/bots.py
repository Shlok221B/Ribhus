"""Bot roster API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ribhus.bots.store import BOT_COLORS
from ribhus.memory.service import MemoryService
from ribhus.web.auth import AuthDep

router = APIRouter(prefix="/api/bots", tags=["bots"])


def _bots(request: Request):
    return request.app.state.bot_store


def _chats(request: Request):
    return request.app.state.chat_store


def _orch(request: Request):
    return request.app.state.bot_orchestrator


class CreateBotBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    job: str = Field(default="", max_length=8_000)
    label: str = Field(default="", max_length=120)
    color: str = Field(default="copper", max_length=32)
    make_primary: bool = False


class UpdateBotBody(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    job: str | None = Field(default=None, max_length=8_000)
    label: str | None = Field(default=None, max_length=120)
    color: str | None = Field(default=None, max_length=32)
    is_primary: bool | None = None


@router.get("")
def list_bots(request: Request, _: AuthDep) -> list[dict[str, Any]]:
    return [b.to_dict() for b in _bots(request).list()]


@router.get("/colors")
def list_colors(_: AuthDep) -> list[str]:
    return list(BOT_COLORS)


@router.post("")
def create_bot(
    request: Request, body: CreateBotBody, _: AuthDep
) -> dict[str, Any]:
    try:
        bot = _bots(request).create(
            name=body.name,
            job=body.job,
            label=body.label,
            color=body.color,
            make_primary=body.make_primary,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _chats(request).direct_for_bot(bot.id, bot_name=bot.name)
    return bot.to_dict()


@router.get("/{bot_id}")
def get_bot(bot_id: str, request: Request, _: AuthDep) -> dict[str, Any]:
    bot = _bots(request).get(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    chat = _chats(request).direct_for_bot(bot.id, bot_name=bot.name)
    data = bot.to_dict()
    data["chat_id"] = chat.id
    return data


@router.patch("/{bot_id}")
def update_bot(
    bot_id: str, body: UpdateBotBody, request: Request, _: AuthDep
) -> dict[str, Any]:
    fields = body.model_dump(exclude_unset=True)
    try:
        bot = _bots(request).update(bot_id, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    # Keep direct chat title in sync with name.
    chat = _chats(request).direct_for_bot(bot.id, bot_name=bot.name)
    if fields.get("name"):
        _chats(request).update(chat.id, title=bot.name)
    return bot.to_dict()


@router.post("/{bot_id}/primary")
def set_primary(bot_id: str, request: Request, _: AuthDep) -> dict[str, Any]:
    bot = _bots(request).set_primary(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    return bot.to_dict()


@router.delete("/{bot_id}")
def delete_bot(bot_id: str, request: Request, _: AuthDep) -> dict[str, Any]:
    store = _bots(request)
    if len(store.list()) <= 1:
        raise HTTPException(
            status_code=400, detail="Cannot delete the last bot"
        )
    bot = store.delete(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    _chats(request).delete_for_bot(bot_id)
    settings = request.app.state.settings
    memory = MemoryService.from_path(
        settings.ribhus_dir / "memory.sqlite",
        env_enabled=settings.memory_enabled,
    )
    try:
        deleted = memory.store.delete_for_bot(bot_id)
    finally:
        memory.close()
    return {"ok": True, "deleted_bot": bot.to_dict(), "memories_removed": deleted}
