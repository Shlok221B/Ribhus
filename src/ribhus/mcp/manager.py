from __future__ import annotations

import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters

from ribhus.mcp.config import (
    McpServerConfig,
    default_mcp_config_path,
    load_mcp_config,
)
from ribhus.mcp.tool import McpProxyTool
from ribhus.tools.registry import ToolRegistry


class McpManager:
    """Connect configured MCP stdio servers and expose them as Ribhus tools."""

    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self._entered = False
        self._clients: dict[str, Client] = {}
        self._configs: dict[str, McpServerConfig] = {}
        self._tools: list[McpProxyTool] = []
        self._errors: list[str] = []

    @property
    def tools(self) -> list[McpProxyTool]:
        return list(self._tools)

    @property
    def errors(self) -> list[str]:
        return list(self._errors)

    @property
    def connected_servers(self) -> list[str]:
        return sorted(self._clients)

    def status(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for name, cfg in self._configs.items():
            tool_names = [
                t.remote_name for t in self._tools if t.server_name == name
            ]
            rows.append(
                {
                    "name": name,
                    "enabled": cfg.enabled,
                    "connected": name in self._clients,
                    "command": cfg.command,
                    "risk": cfg.risk,
                    "tools": tool_names,
                }
            )
        return rows

    async def connect(
        self,
        servers: list[McpServerConfig],
        *,
        workspace: Path | None = None,
    ) -> None:
        if not self._entered:
            await self._stack.__aenter__()
            self._entered = True

        for cfg in servers:
            self._configs[cfg.name] = cfg
            if not cfg.enabled:
                continue
            if cfg.name in self._clients:
                continue
            try:
                client = await self._open_client(cfg, workspace=workspace)
                self._clients[cfg.name] = client
                listed = await client.list_tools()
                for remote in listed.tools:
                    schema = getattr(remote, "input_schema", None) or {}
                    if hasattr(schema, "model_dump"):
                        schema = schema.model_dump()
                    if not isinstance(schema, dict):
                        schema = {"type": "object", "properties": {}}
                    proxy = McpProxyTool(
                        server_name=cfg.name,
                        remote_name=remote.name,
                        description=remote.description or remote.name,
                        input_schema=schema,
                        risk=cfg.risk,
                        caller=self._make_caller(cfg.name),
                    )
                    self._tools.append(proxy)
            except Exception as exc:  # noqa: BLE001
                self._errors.append(f"{cfg.name}: {exc}")

    async def connect_from_path(
        self,
        path: Path,
        *,
        workspace: Path | None = None,
    ) -> None:
        await self.connect(load_mcp_config(path), workspace=workspace)

    async def connect_from_workspace(self, workspace: Path) -> None:
        path = default_mcp_config_path(workspace)
        override = os.getenv("RIBHUS_MCP_CONFIG", "").strip()
        if override:
            path = Path(override)
        await self.connect_from_path(path, workspace=workspace)

    def register_into(self, registry: ToolRegistry) -> int:
        count = 0
        for tool in self._tools:
            if registry.get(tool.name) is None:
                registry.register(tool)
                count += 1
        return count

    async def close(self) -> None:
        self._clients.clear()
        self._tools.clear()
        if self._entered:
            await self._stack.aclose()
            self._entered = False
            self._stack = AsyncExitStack()

    async def _open_client(
        self,
        cfg: McpServerConfig,
        *,
        workspace: Path | None,
    ) -> Client:
        env = None
        if cfg.env:
            env = {**os.environ, **cfg.env}
        cwd = cfg.cwd or (str(workspace) if workspace else None)
        params = StdioServerParameters(
            command=cfg.command,
            args=cfg.args,
            env=env,
            cwd=cwd,
        )
        return await self._stack.enter_async_context(Client(params))

    def _make_caller(self, server_name: str):
        async def _call(remote_name: str, arguments: dict[str, Any]):
            client = self._clients.get(server_name)
            if client is None:
                raise RuntimeError(f"MCP server '{server_name}' is not connected")
            return await client.call_tool(remote_name, arguments)

        return _call


async def start_mcp_manager(
    workspace: Path,
    *,
    enabled: bool = True,
    config_path: Path | None = None,
) -> McpManager | None:
    """Start MCP if enabled and config exists. Returns None when unused."""
    if not enabled:
        return None
    env_flag = os.getenv("RIBHUS_MCP_ENABLED", "").strip().lower()
    if env_flag in {"0", "false", "no", "off"}:
        return None
    path = config_path or default_mcp_config_path(workspace)
    override = os.getenv("RIBHUS_MCP_CONFIG", "").strip()
    if override:
        path = Path(override)
    if not path.exists():
        return None
    manager = McpManager()
    await manager.connect_from_path(path, workspace=workspace)
    return manager


def register_mcp_tools(registry: ToolRegistry, manager: McpManager | None) -> None:
    if manager is None:
        return
    manager.register_into(registry)
