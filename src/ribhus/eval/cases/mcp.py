from __future__ import annotations

import sys

from ribhus.eval.harness import repo_root, temp_workspace
from ribhus.eval.models import EvalCase, EvalSkip
from ribhus.mcp.config import McpServerConfig, example_mcp_config, load_mcp_config
from ribhus.mcp.manager import McpManager
from ribhus.tools.registry import default_registry


def example_config_shape() -> None:
    with temp_workspace() as workspace:
        payload = example_mcp_config(workspace)
        assert "demo" in payload["mcpServers"]
        path = workspace / ".ribhus" / "mcp.json"
        path.write_text(
            '{"mcpServers": {"demo": {"command": "uv", "args": ["run", "python", "x.py"], "risk": "low"}}}',
            encoding="utf-8",
        )
        servers = load_mcp_config(path)
        assert len(servers) == 1
        assert servers[0].name == "demo"
        assert servers[0].risk == "low"


async def demo_server_tools() -> None:
    root = repo_root()
    if root is None:
        raise EvalSkip("MCP demo server lives in the git checkout")
    demo = root / "examples" / "mcp_demo_server.py"
    if not demo.is_file():
        raise EvalSkip(f"missing {demo}")
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
        if manager.errors:
            raise EvalSkip(f"demo MCP server failed: {manager.errors}")
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


CASES = [
    EvalCase("mcp-config", "mcp", "mcp.config", "Example MCP config loads", example_config_shape),
    EvalCase("mcp-demo-server", "mcp", "mcp.manager", "Demo server exposes demo__add", demo_server_tools),
]
