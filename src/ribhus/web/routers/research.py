"""API for persisted deep-research runs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ribhus.config import get_settings
from ribhus.research.store import ResearchStore
from ribhus.web.auth import AuthDep

router = APIRouter(prefix="/api/research", tags=["research"])


def _store() -> ResearchStore:
    settings = get_settings()
    return ResearchStore(settings.ribhus_dir / "research.sqlite")


@router.get("/runs")
def list_runs(_: AuthDep, limit: int = 20) -> list[dict[str, Any]]:
    return _store().list_recent(limit=limit)


@router.get("/runs/{run_id}")
def get_run(run_id: str, _: AuthDep) -> dict[str, Any]:
    detail = _store().get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Research run not found")
    return detail


@router.get("/by-task/{task_id}")
def get_by_task(task_id: str, _: AuthDep) -> dict[str, Any]:
    store = _store()
    run = store.latest_for_task(task_id)
    if run is None:
        raise HTTPException(status_code=404, detail="No research run for task")
    detail = store.get_run_detail(str(run["id"]))
    if detail is None:
        raise HTTPException(status_code=404, detail="Research run not found")
    return detail
