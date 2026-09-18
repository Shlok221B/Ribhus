from __future__ import annotations

import json

import pytest

from ribhus.tools.registry import default_registry
from ribhus.tools.todo import TodoStore, TodoTool


def test_default_registry_includes_todo(tmp_path):
    assert "todo" in default_registry(tmp_path).names()


def test_default_registry_shares_todo_store(tmp_path):
    store = TodoStore()
    tool = default_registry(tmp_path, todo_store=store).get("todo")
    assert tool is not None
    assert tool.store is store


@pytest.mark.asyncio
async def test_todo_read_empty():
    tool = TodoTool()
    payload = json.loads(await tool.execute({}))
    assert payload["todos"] == []
    assert payload["summary"]["total"] == 0


@pytest.mark.asyncio
async def test_todo_replace_and_merge():
    tool = TodoTool()
    created = json.loads(
        await tool.execute(
            {
                "todos": [
                    {
                        "id": "1",
                        "content": "Research company",
                        "status": "in_progress",
                    },
                    {"id": "2", "content": "Draft brief", "status": "pending"},
                    {"id": "3", "content": "WhatsApp send", "status": "pending"},
                ]
            }
        )
    )
    assert created["summary"]["total"] == 3
    assert created["summary"]["in_progress"] == 1

    merged = json.loads(
        await tool.execute(
            {
                "merge": True,
                "todos": [
                    {"id": "1", "content": "Research company", "status": "completed"},
                    {"id": "2", "content": "Draft brief", "status": "in_progress"},
                ],
            }
        )
    )
    by_id = {item["id"]: item for item in merged["todos"]}
    assert by_id["1"]["status"] == "completed"
    assert by_id["2"]["status"] == "in_progress"
    assert by_id["3"]["status"] == "pending"
    assert merged["summary"]["completed"] == 1


@pytest.mark.asyncio
async def test_todo_warns_multiple_in_progress():
    tool = TodoTool()
    payload = json.loads(
        await tool.execute(
            {
                "todos": [
                    {"id": "a", "content": "One", "status": "in_progress"},
                    {"id": "b", "content": "Two", "status": "in_progress"},
                ]
            }
        )
    )
    assert "warning" in payload


@pytest.mark.asyncio
async def test_todo_invalid_status_defaults_pending():
    store = TodoStore()
    store.write([{"id": "x", "content": "Thing", "status": "nope"}])
    assert store.read()[0]["status"] == "pending"


def test_todo_format_display():
    store = TodoStore()
    store.write(
        [
            {"id": "1", "content": "Search", "status": "completed"},
            {"id": "2", "content": "Extract", "status": "in_progress"},
        ]
    )
    text = store.format_display()
    assert text is not None
    assert "[x] 1:" in text
    assert "[>] 2:" in text


@pytest.mark.asyncio
async def test_todo_preflight_rejects_non_list():
    tool = TodoTool()
    assert tool.preflight({"todos": "nope"}) is not None
