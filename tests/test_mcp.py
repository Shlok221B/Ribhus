from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from ribhus.mcp.config import (
    McpServerConfig,
    example_mcp_config,
    load_mcp_config,
)
from ribhus.mcp.manager import McpManager
from ribhus.tools.registry import default_registry


def test_load_mcp_config_missing(tmp_path: Path):
    assert load_mcp_config(tmp_path / "missing.json") == []


def test_load_mcp_config_valid(tmp_path: Path):
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "demo": {
                        "command": "uv",
                        "args": ["run", "python", "examples/mcp_demo_server.py"],
                        "risk": "low",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    servers = load_mcp_config(path)
    assert len(servers) == 1
    assert servers[0].name == "demo"
    assert servers[0].risk == "low"


def test_load_mcp_config_rejects_bad_name(tmp_path: Path):
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps({"mcpServers": {"bad name": {"command": "x"}}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Invalid server name"):
        load_mcp_config(path)


def test_example_mcp_config_shape(tmp_path: Path):
    payload = example_mcp_config(tmp_path)
    assert "demo" in payload["mcpServers"]


@pytest.mark.asyncio
async def test_mcp_manager_connects_demo_server():
    root = Path(__file__).resolve().parents[1]
    demo = root / "examples" / "mcp_demo_server.py"
    assert demo.exists()
    manager = McpManager()
    try:
        await manager.connect(
            [
                McpServerConfig(
                    name="demo",
                    command=sys.executable,
                    args=[str(demo)],
                    risk="low",
                )
            ],
            workspace=root,
        )
        assert manager.errors == []
        assert "demo" in manager.connected_servers
        names = {t.name for t in manager.tools}
        assert "demo__add" in names
        assert "demo__echo" in names

        add = next(t for t in manager.tools if t.name == "demo__add")
        result = await add.execute({"a": 2, "b": 40})
        assert "42" in result

        registry = default_registry(root, mcp_manager=manager)
        assert "demo__add" in registry.names()
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_mcp_manager_records_connect_error():
    manager = McpManager()
    try:
        await manager.connect(
            [
                McpServerConfig(
                    name="gone",
                    command="this-binary-does-not-exist-ribhus",
                    args=[],
                    risk="medium",
                )
            ]
        )
        assert manager.errors
        assert manager.tools == []
    finally:
        await manager.close()
