"""Direct and group chat API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ribhus.web.auth import AuthDep

router = APIRouter(prefix="/api/chats", tags=["chats"])


def _chats(request: Request):
    return request.app.state.chat_store


def _bots(request: Request):
    return request.app.state.bot_store


def _orch(request: Request):
    return request.app.state.bot_orchestrator


class CreateGroupBody(BaseModel):
    bot_ids: list[str] = Field(min_length=2, max_length=6)
    title: str = Field(default="", max_length=200)


class UpdateChatBody(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    bot_ids: list[str] | None = None


class PostMessageBody(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)


@router.get("")
def list_chats(request: Request, _: AuthDep) -> list[dict[str, Any]]:
    orch = _orch(request)
    orch.ensure_direct_chats()
    return [c.to_dict() for c in _chats(request).list()]


@router.post("/group")
def create_group(
    request: Request, body: CreateGroupBody, _: AuthDep
) -> dict[str, Any]:
    bots = _bots(request)
    for bot_id in body.bot_ids:
        if bots.get(bot_id) is None:
            raise HTTPException(
                status_code=400, detail=f"Unknown bot: {bot_id}"
            )
    names = {b.id: b.name for b in bots.list()}
    try:
        chat = _chats(request).create_group(
            bot_ids=body.bot_ids,
            title=body.title,
            bot_names=names,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return chat.to_dict()


@router.get("/{chat_id}")
def get_chat(chat_id: str, request: Request, _: AuthDep) -> dict[str, Any]:
    chat = _chats(request).get(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    data = chat.to_dict()
    bot_map = {b.id: b.to_dict() for b in _bots(request).list()}
    data["bots"] = [bot_map[bid] for bid in chat.bot_ids if bid in bot_map]
    return data


@router.patch("/{chat_id}")
def update_chat(
    chat_id: str, body: UpdateChatBody, request: Request, _: AuthDep
) -> dict[str, Any]:
    try:
        chat = _chats(request).update(
            chat_id,
            title=body.title,
            bot_ids=body.bot_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat.to_dict()


@router.delete("/{chat_id}")
def delete_chat(chat_id: str, request: Request, _: AuthDep) -> dict[str, Any]:
    chat = _chats(request).get(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    if chat.kind == "direct":
        raise HTTPException(
            status_code=400,
            detail="Direct chats are removed when you delete the bot",
        )
    _chats(request).delete(chat_id)
    return {"ok": True}


@router.post("/{chat_id}/messages")
async def post_message(
    chat_id: str, body: PostMessageBody, request: Request, _: AuthDep
) -> dict[str, Any]:
    orch = _orch(request)
    try:
        result = orch.enqueue_user_message(chat_id, body.content)
    except KeyError:
        raise HTTPException(status_code=404, detail="Chat not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.get("/by-bot/{bot_id}")
def direct_chat_for_bot(
    bot_id: str, request: Request, _: AuthDep
) -> dict[str, Any]:
    bot = _bots(request).get(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    chat = _chats(request).direct_for_bot(bot.id, bot_name=bot.name)
    data = chat.to_dict()
    data["bots"] = [bot.to_dict()]
    return data
