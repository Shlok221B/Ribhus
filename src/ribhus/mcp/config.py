from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")


@dataclass
class McpServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    risk: str = "medium"  # low|medium|high|critical
    cwd: str | None = None

    def validate(self) -> str | None:
        if not _NAME_RE.match(self.name):
            return (
                f"Invalid server name '{self.name}' "
                "(use letters, digits, _ or -; start with a letter)"
            )
        if not self.command.strip():
            return f"Server '{self.name}' is missing command"
        if self.risk.lower() not in {"low", "medium", "high", "critical"}:
            return f"Server '{self.name}' has invalid risk '{self.risk}'"
        return None


def default_mcp_config_path(workspace: Path) -> Path:
    return workspace / ".ribhus" / "mcp.json"


def example_mcp_config(workspace: Path) -> dict[str, Any]:
    demo = workspace / "examples" / "mcp_demo_server.py"
    return {
        "mcpServers": {
            "demo": {
                "command": "uv",
                "args": ["run", "python", str(demo)],
                "enabled": True,
                "risk": "low",
            },
            "github": {
                "command": "docker",
                "args": [
                    "run",
                    "-i",
                    "--rm",
                    "-e",
                    "GITHUB_PERSONAL_ACCESS_TOKEN",
                    "ghcr.io/github/github-mcp-server",
                ],
                "enabled": True,
                "risk": "high",
            },
        }
    }


def load_mcp_config(path: Path) -> list[McpServerConfig]:
    """Load `.ribhus/mcp.json`. Missing file → empty list."""
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid MCP config JSON ({path}): {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"MCP config root must be an object ({path})")

    servers_raw = raw.get("mcpServers") or raw.get("servers") or {}
    if not isinstance(servers_raw, dict):
        raise ValueError("mcpServers must be an object")

    out: list[McpServerConfig] = []
    for name, cfg in servers_raw.items():
        if not isinstance(cfg, dict):
            raise ValueError(f"Server '{name}' config must be an object")
        server = McpServerConfig(
            name=str(name).strip(),
            command=str(cfg.get("command") or "").strip(),
            args=[str(a) for a in (cfg.get("args") or [])],
            env={str(k): str(v) for k, v in (cfg.get("env") or {}).items()},
            enabled=bool(cfg.get("enabled", True)),
            risk=str(cfg.get("risk") or "medium").lower(),
            cwd=str(cfg["cwd"]) if cfg.get("cwd") else None,
        )
        err = server.validate()
        if err:
            raise ValueError(err)
        out.append(server)
    return out
