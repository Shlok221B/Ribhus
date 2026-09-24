from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ribhus import __version__
from ribhus.config import get_settings
from ribhus.web.auth import AuthDep

router = APIRouter(prefix="/api/config", tags=["config"])

_SAFE_BOOL_KEYS = {
    "auto_approve": "RIBHUS_AUTO_APPROVE",
    "memory_enabled": "RIBHUS_MEMORY_ENABLED",
    "mcp_enabled": "RIBHUS_MCP_ENABLED",
    "whatsapp_enabled": "RIBHUS_WHATSAPP_ENABLED",
    "email_enabled": "RIBHUS_EMAIL_ENABLED",
}

_SAFE_STR_KEYS = {
    "model": "RIBHUS_MODEL",
    "base_url": "RIBHUS_BASE_URL",
    "approve_at": "RIBHUS_APPROVE_AT",
}


class ConfigPatch(BaseModel):
    model: str | None = Field(default=None, max_length=200)
    base_url: str | None = Field(default=None, max_length=500)
    auto_approve: bool | None = None
    approve_at: str | None = Field(default=None, max_length=20)
    memory_enabled: bool | None = None
    mcp_enabled: bool | None = None
    whatsapp_enabled: bool | None = None
    email_enabled: bool | None = None


def _mask_key(key: str) -> str:
    if not key:
        return "(not set)"
    if len(key) <= 8:
        return "***"
    return f"{key[:3]}…{key[-4:]}"


def _safe_config() -> dict[str, Any]:
    settings = get_settings()
    return {
        "model": settings.model,
        "base_url": settings.base_url,
        "api_key_set": bool(settings.api_key),
        "api_key_masked": _mask_key(settings.api_key),
        "auto_approve": settings.auto_approve,
        "approve_at": settings.approve_at,
        "memory_enabled": settings.memory_enabled,
        "mcp_enabled": settings.mcp_enabled,
        "whatsapp_enabled": settings.whatsapp_enabled,
        "email_enabled": settings.email_enabled,
        "browser_headed": settings.browser_headed,
        "workspace": str(settings.workspace),
        "ribhus_dir": str(settings.ribhus_dir),
        "version": __version__,
    }


def _env_file() -> Path:
    settings = get_settings()
    # Prefer workspace .env, then cwd.
    for candidate in (settings.workspace / ".env", Path.cwd() / ".env"):
        if candidate.exists():
            return candidate
    return settings.workspace / ".env"


def _upsert_env(path: Path, updates: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        matched = False
        for key, value in updates.items():
            if re.match(rf"^\s*{re.escape(key)}\s*=", line):
                out.append(f"{key}={value}")
                seen.add(key)
                matched = True
                break
        if not matched:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


@router.get("")
def get_config(_: AuthDep) -> dict[str, Any]:
    return _safe_config()


@router.patch("")
def patch_config(body: ConfigPatch, _: AuthDep) -> dict[str, Any]:
    data = body.model_dump(exclude_unset=True)
    if not data:
        return _safe_config()
    if "approve_at" in data and data["approve_at"] not in {
        "low",
        "medium",
        "high",
        "critical",
    }:
        raise HTTPException(status_code=400, detail="Invalid approve_at")

    env_updates: dict[str, str] = {}
    for field, env_key in _SAFE_STR_KEYS.items():
        if field in data and data[field] is not None:
            env_updates[env_key] = str(data[field])
            os.environ[env_key] = str(data[field])
    for field, env_key in _SAFE_BOOL_KEYS.items():
        if field in data and data[field] is not None:
            val = "true" if data[field] else "false"
            env_updates[env_key] = val
            os.environ[env_key] = val

    if env_updates:
        _upsert_env(_env_file(), env_updates)

    # Clear cached settings if any — Settings() re-reads env each get_settings call
    return _safe_config()
