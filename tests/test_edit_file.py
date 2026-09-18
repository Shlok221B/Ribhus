from __future__ import annotations

import pytest

from ribhus.tools.filesystem import EditFileTool
from ribhus.tools.registry import default_registry


def test_default_registry_includes_edit_file(tmp_path):
    assert "edit_file" in default_registry(tmp_path).names()


@pytest.mark.asyncio
async def test_edit_file_unique_replace(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    tool = EditFileTool(workspace=tmp_path)
    result = await tool.execute(
        {"path": "note.txt", "old_string": "beta", "new_string": "BETA"}
    )
    assert "1 replacement" in result
    assert path.read_text(encoding="utf-8") == "alpha\nBETA\ngamma\n"


@pytest.mark.asyncio
async def test_edit_file_requires_unique_match(tmp_path):
    path = tmp_path / "dup.txt"
    path.write_text("x=1\nx=2\n", encoding="utf-8")
    tool = EditFileTool(workspace=tmp_path)
    result = await tool.execute(
        {"path": "dup.txt", "old_string": "x=", "new_string": "y="}
    )
    assert "Error" in result
    assert "2 times" in result
    assert path.read_text(encoding="utf-8") == "x=1\nx=2\n"


@pytest.mark.asyncio
async def test_edit_file_replace_all(tmp_path):
    path = tmp_path / "dup.txt"
    path.write_text("x=1\nx=2\n", encoding="utf-8")
    tool = EditFileTool(workspace=tmp_path)
    result = await tool.execute(
        {
            "path": "dup.txt",
            "old_string": "x=",
            "new_string": "y=",
            "replace_all": True,
        }
    )
    assert "2 replacement" in result
    assert path.read_text(encoding="utf-8") == "y=1\ny=2\n"


@pytest.mark.asyncio
async def test_edit_file_not_found(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("hello world\n", encoding="utf-8")
    tool = EditFileTool(workspace=tmp_path)
    result = await tool.execute(
        {"path": "a.txt", "old_string": "goodbye", "new_string": "hi"}
    )
    assert "not found" in result.lower()


@pytest.mark.asyncio
async def test_edit_file_delete_via_empty_new(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("keep\nremove-me\nkeep2\n", encoding="utf-8")
    tool = EditFileTool(workspace=tmp_path)
    await tool.execute(
        {"path": "a.txt", "old_string": "remove-me\n", "new_string": ""}
    )
    assert path.read_text(encoding="utf-8") == "keep\nkeep2\n"


@pytest.mark.asyncio
async def test_edit_file_preflight_identical(tmp_path):
    tool = EditFileTool(workspace=tmp_path)
    blocked = tool.preflight(
        {"path": "a.txt", "old_string": "same", "new_string": "same"}
    )
    assert blocked is not None
    assert "identical" in blocked.lower()


@pytest.mark.asyncio
async def test_edit_file_outside_workspace(tmp_path):
    tool = EditFileTool(workspace=tmp_path)
    result = await tool.execute(
        {
            "path": "../escape.txt",
            "old_string": "a",
            "new_string": "b",
        }
    )
    assert "Error" in result
    assert "outside" in result.lower()
