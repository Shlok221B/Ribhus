from __future__ import annotations

import pytest

from ribhus.tools.filesystem import ReadFileTool, WriteFileTool, _resolve_path
from ribhus.tools.registry import ToolRegistry, default_registry
from ribhus.tools.terminal import TerminalTool
from ribhus.tools.python_exec import PythonTool
from ribhus.agent.state import AgentState


def test_default_registry_has_phase1_tools(tmp_path):
    registry = default_registry(tmp_path)
    assert registry.names() == [
        "clarify",
        "http_request",
        "process",
        "python",
        "read_file",
        "terminal",
        "web_extract",
        "web_search",
        "write_file",
    ]


@pytest.mark.asyncio
async def test_registry_unknown_tool():
    registry = ToolRegistry()
    result = await registry.execute("nope", {})
    assert "unknown tool" in result


@pytest.mark.asyncio
async def test_write_and_read_file(tmp_path):
    write = WriteFileTool(workspace=tmp_path)
    read = ReadFileTool(workspace=tmp_path)
    await write.execute({"path": "hello.txt", "content": "namaste"})
    content = await read.execute({"path": "hello.txt"})
    assert content == "namaste"


@pytest.mark.asyncio
async def test_path_escape_blocked(tmp_path):
    read = ReadFileTool(workspace=tmp_path)
    result = await read.execute({"path": "../outside.txt"})
    assert "outside the workspace" in result


@pytest.mark.asyncio
async def test_python_tool(tmp_path):
    tool = PythonTool(workspace=tmp_path)
    result = await tool.execute({"code": "print(2 + 2)"})
    assert "exit_code=0" in result
    assert "4" in result


@pytest.mark.asyncio
async def test_terminal_tool(tmp_path):
    tool = TerminalTool(workspace=tmp_path)
    result = await tool.execute({"command": "echo ribhus"})
    assert "exit_code=0" in result
    assert "ribhus" in result


@pytest.mark.asyncio
async def test_terminal_blocks_dangerous(tmp_path):
    tool = TerminalTool(workspace=tmp_path)
    result = await tool.execute({"command": "rm -rf /"})
    assert "blocked" in result


@pytest.mark.asyncio
async def test_terminal_blocks_playwright_install(tmp_path):
    tool = TerminalTool(workspace=tmp_path)
    result = await tool.execute({"command": "playwright install"})
    assert "blocked" in result


def test_agent_state_finish():
    state = AgentState()
    state.add_user("hi")
    state.finish("done")
    assert state.finished
    assert state.final_text == "done"
    assert state.messages[0]["role"] == "user"


def test_resolve_path_inside(tmp_path):
    target = tmp_path / "a" / "b.txt"
    target.parent.mkdir(parents=True)
    target.write_text("x")
    resolved = _resolve_path(tmp_path, "a/b.txt")
    assert resolved == target.resolve()


def test_tool_openai_schema():
    from ribhus.tools.web_search import WebSearchTool

    schema = WebSearchTool().openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "web_search"
    assert "query" in schema["function"]["parameters"]["properties"]
