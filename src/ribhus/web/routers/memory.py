from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ribhus.config import get_settings
from ribhus.memory.service import MemoryService
from ribhus.web.auth import AuthDep

router = APIRouter(prefix="/api/memory", tags=["memory"])


class AddMemoryBody(BaseModel):
    content: str = Field(min_length=1, max_length=8_000)
    key: str | None = None


def _memory() -> MemoryService:
    settings = get_settings()
    return MemoryService.from_path(
        settings.ribhus_dir / "memory.sqlite",
        env_enabled=settings.memory_enabled,
    )


def _row(record) -> dict[str, Any]:
    return {
        "id": record.id,
        "kind": record.kind,
        "key": record.key,
        "content": record.content,
        "disabled": record.disabled,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


@router.get("")
def list_or_search(
    _: AuthDep,
    q: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    svc = _memory()
    try:
        if q and q.strip():
            rows = svc.search(q.strip(), limit=limit)
        else:
            rows = svc.list(limit=limit)
        return [_row(r) for r in rows]
    finally:
        svc.close()


@router.post("")
def add_memory(body: AddMemoryBody, _: AuthDep) -> dict[str, Any]:
    svc = _memory()
    try:
        record = svc.add(body.content, kind="semantic", key=body.key)
        return _row(record)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        svc.close()


@router.delete("/{target}")
def forget_memory(target: str, _: AuthDep) -> dict[str, str]:
    svc = _memory()
    try:
        forgotten = svc.forget(target)
        return {"forgotten": forgotten}
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        svc.close()
