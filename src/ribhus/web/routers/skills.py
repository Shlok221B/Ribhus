from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ribhus.config import get_settings
from ribhus.skills.installer import install_skill_with_warnings, remove_skill
from ribhus.skills.package import SkillPackageError
from ribhus.skills.registry import SkillRegistry
from ribhus.web.auth import AuthDep

router = APIRouter(prefix="/api/skills", tags=["skills"])


class InstallBody(BaseModel):
    source: str = Field(min_length=1, max_length=500)


def _skill_row(skill, *, installed: bool) -> dict[str, Any]:
    return {
        "name": skill.name,
        "version": skill.config.version,
        "description": skill.config.description,
        "triggers": list(skill.config.triggers),
        "installed": installed,
        "path": str(skill.path),
    }


@router.get("")
def list_skills(_: AuthDep) -> list[dict[str, Any]]:
    settings = get_settings()
    registry = SkillRegistry.load_default(settings.workspace)
    installed_root = settings.workspace / ".ribhus" / "skills"
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for skill in registry.list():
        installed = False
        try:
            installed = skill.path.resolve().is_relative_to(installed_root.resolve())
        except (ValueError, OSError):
            installed = ".ribhus/skills" in str(skill.path)
        if skill.name in seen:
            continue
        seen.add(skill.name)
        rows.append(_skill_row(skill, installed=installed))
    return rows


@router.post("/install")
def install_skill_endpoint(body: InstallBody, _: AuthDep) -> dict[str, Any]:
    settings = get_settings()
    try:
        skill, _warnings = install_skill_with_warnings(
            body.source, workspace=settings.workspace
        )
    except (FileNotFoundError, FileExistsError, ValueError, SkillPackageError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _skill_row(skill, installed=True)


@router.delete("/{name}")
def remove_skill_endpoint(name: str, _: AuthDep) -> dict[str, bool]:
    settings = get_settings()
    try:
        remove_skill(name, workspace=settings.workspace)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}
