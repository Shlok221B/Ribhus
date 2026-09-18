from __future__ import annotations

import asyncio
import json
import sys

import pytest

from ribhus.tools.process import ProcessTool, make_process_tool
from ribhus.tools.process_registry import ProcessRegistry
from ribhus.tools.registry import default_registry


def test_default_registry_includes_process(tmp_path):
    assert "process" in default_registry(tmp_path).names()


@pytest.mark.asyncio
async def test_process_start_wait_exit(tmp_path):
    tool = make_process_tool(tmp_path)
    started = json.loads(
        await tool.execute(
            {
                "action": "start",
                "command": f"{sys.executable} -c \"print('hello-bg')\"",
            }
        )
    )
    assert started["status"] == "running"
    sid = started["session_id"]
    assert sid.startswith("proc_")

    finished = json.loads(
        await tool.execute({"action": "wait", "session_id": sid, "timeout": 10})
    )
    assert finished["status"] == "exited"
    assert finished["exit_code"] == 0
    assert "hello-bg" in finished.get("output_tail", "")

    listed = json.loads(await tool.execute({"action": "list"}))
    assert any(p["session_id"] == sid for p in listed["processes"])


@pytest.mark.asyncio
async def test_process_poll_and_kill(tmp_path):
    tool = make_process_tool(tmp_path)
    started = json.loads(
        await tool.execute(
            {
                "action": "start",
                "command": f"{sys.executable} -c \"import time; print('tick', flush=True); time.sleep(30)\"",
            }
        )
    )
    sid = started["session_id"]
    await asyncio.sleep(0.3)
    polled = json.loads(await tool.execute({"action": "poll", "session_id": sid}))
    assert polled["status"] == "running"
    assert "tick" in polled.get("new_output", "")

    killed = json.loads(await tool.execute({"action": "kill", "session_id": sid}))
    assert killed["status"] in {"killed", "exited"}
    assert killed["exit_code"] is not None


@pytest.mark.asyncio
async def test_process_write_submit(tmp_path):
    tool = make_process_tool(tmp_path)
    started = json.loads(
        await tool.execute(
            {
                "action": "start",
                "command": (
                    f"{sys.executable} -c \""
                    "import sys; line=sys.stdin.readline(); print('got:'+line.strip(), flush=True)\""
                ),
            }
        )
    )
    sid = started["session_id"]
    wrote = json.loads(
        await tool.execute({"action": "submit", "session_id": sid, "data": "namaste"})
    )
    assert wrote["status"] == "ok"
    finished = json.loads(
        await tool.execute({"action": "wait", "session_id": sid, "timeout": 10})
    )
    assert finished["exit_code"] == 0
    assert "got:namaste" in finished.get("output_tail", "")


@pytest.mark.asyncio
async def test_process_blocks_dangerous_command(tmp_path):
    tool = make_process_tool(tmp_path)
    blocked = tool.preflight({"action": "start", "command": "rm -rf /"})
    assert blocked is not None
    assert "blocked" in blocked.lower()


@pytest.mark.asyncio
async def test_process_log_pagination(tmp_path):
    registry = ProcessRegistry(tmp_path)
    tool = ProcessTool(registry)
    started = json.loads(
        await tool.execute(
            {
                "action": "start",
                "command": f"{sys.executable} -c \"print('abcdef')\"",
            }
        )
    )
    sid = started["session_id"]
    await tool.execute({"action": "wait", "session_id": sid, "timeout": 10})
    page = json.loads(
        await tool.execute(
            {"action": "log", "session_id": sid, "offset": 0, "limit": 3}
        )
    )
    assert page["output"]
    assert page["next_offset"] == len(page["output"])


@pytest.mark.asyncio
async def test_process_risk_levels(tmp_path):
    tool = make_process_tool(tmp_path)
    assert tool.risk_for_arguments({"action": "list"}).value == "low"
    assert tool.risk_for_arguments({"action": "poll"}).value == "low"
    assert tool.risk_for_arguments({"action": "wait"}).value == "medium"
    assert tool.risk_for_arguments({"action": "start"}).value == "high"
    assert tool.risk_for_arguments({"action": "kill"}).value == "high"
