"""Direct and group chat API."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from ribhus.web.auth import AuthDep

router = APIRouter(prefix="/api/chats", tags=["chats"])

_MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_ALLOWED_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".tex",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".xml",
    ".pdf",
    ".docx",
    ".doc",
    ".rtf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".svg",
}


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


@router.post("/{chat_id}/uploads")
async def upload_chat_file(
    chat_id: str,
    request: Request,
    _: AuthDep,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Save a file into the workspace so the bot can read_file it."""
    chat = _chats(request).get(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    original = (file.filename or "upload").strip() or "upload"
    # Keep only the basename — never trust client paths.
    original = Path(original).name
    suffix = Path(original).suffix.lower()
    if suffix and suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. "
            "Try text, PDF, DOCX, images, or code/config files.",
        )

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File too large (max {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB)",
        )

    stem = _SAFE_NAME.sub("_", Path(original).stem).strip("._") or "upload"
    safe_name = f"{stem}{suffix}"
    settings = request.app.state.settings
    rel_dir = Path(".ribhus") / "uploads" / chat_id
    dest_dir: Path = settings.workspace / rel_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Prefix with short id so same-name re-uploads don't collide.
    unique = f"{uuid.uuid4().hex[:8]}_{safe_name}"
    dest = dest_dir / unique
    dest.write_bytes(raw)

    rel_path = str(rel_dir / unique)
    extracted_text: str | None = None
    extract_error: str | None = None
    if suffix in {".pdf", ".docx", ".txt", ".md", ".markdown", ".csv", ".json", ".tex"}:
        try:
            if suffix in {".pdf", ".docx"}:
                from ribhus.tools.filesystem import extract_document_text

                extracted_text = extract_document_text(dest)
            else:
                extracted_text = dest.read_text(encoding="utf-8", errors="replace")
            if extracted_text and len(extracted_text) > 80_000:
                extracted_text = extracted_text[:80_000] + "\n...[truncated]"
        except Exception as exc:  # noqa: BLE001
            extract_error = str(exc)
    return {
        "name": original,
        "path": rel_path,
        "size": len(raw),
        "content_type": file.content_type or "application/octet-stream",
        "extracted_text": extracted_text,
        "extract_error": extract_error,
    }


@router.get("/by-bot/{bot_id}")
async def direct_chat_for_bot(
    bot_id: str, request: Request, _: AuthDep
) -> dict[str, Any]:
    bot = _bots(request).get(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    from ribhus.bots.welcome import seed_direct_welcome

    await seed_direct_welcome(
        chats=_chats(request),
        bot=bot,
        settings=request.app.state.settings,
    )
    chat = _chats(request).direct_for_bot(bot.id, bot_name=bot.name)
    data = chat.to_dict()
    data["bots"] = [bot.to_dict()]
    return data
