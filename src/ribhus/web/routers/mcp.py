from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from ribhus.config import get_settings
from ribhus.mcp.config import default_mcp_config_path, load_mcp_config
from ribhus.mcp.manager import McpManager
from ribhus.web.auth import AuthDep

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


def _config_path() -> Path:
    settings = get_settings()
    if settings.mcp_config.strip():
        return Path(settings.mcp_config.strip())
    return default_mcp_config_path(settings.workspace)


@router.get("")
async def list_mcp(_: AuthDep) -> dict[str, Any]:
    settings = get_settings()
    path = _config_path()
    if not path.exists():
        return {
            "servers": [],
            "errors": [f"No MCP config at {path}. Run: ribhus mcp init"],
            "config_path": str(path),
        }
    try:
        servers = load_mcp_config(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not settings.mcp_enabled:
        return {
            "servers": [
                {
                    "name": s.name,
                    "enabled": False,
                    "connected": False,
                    "command": s.command,
                    "risk": s.risk,
                    "tools": [],
                }
                for s in servers
            ],
            "errors": ["MCP disabled (RIBHUS_MCP_ENABLED=false)"],
            "config_path": str(path),
        }

    manager = McpManager()
    try:
        await manager.connect(servers, workspace=settings.workspace)
        return {
            "servers": manager.status(),
            "errors": manager.errors,
            "config_path": str(path),
        }
    finally:
        await manager.close()


@router.post("/{server}/test")
async def test_mcp(server: str, _: AuthDep) -> dict[str, Any]:
    settings = get_settings()
    path = _config_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No MCP config at {path}")
    servers = load_mcp_config(path)
    match = next((s for s in servers if s.name == server), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"Unknown server '{server}'")
    manager = McpManager()
    try:
        await manager.connect([match], workspace=settings.workspace)
        if server not in manager.connected_servers:
            errs = "; ".join(manager.errors) or "failed to connect"
            raise HTTPException(status_code=400, detail=errs)
        # Prefer demo add, else first tool
        tool_names = [
            t.remote_name for t in manager.tools if t.server_name == server
        ]
        if not tool_names:
            raise HTTPException(status_code=400, detail="Server has no tools")
        remote = "add" if "add" in tool_names else tool_names[0]
        proxy = next(
            t
            for t in manager.tools
            if t.server_name == server and t.remote_name == remote
        )
        args: dict[str, Any] = {"a": 2, "b": 3} if remote == "add" else {}
        result = await proxy.execute(args)
        return {"ok": True, "result": str(result)[:2000]}
    finally:
        await manager.close()
