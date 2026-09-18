from __future__ import annotations

import pytest

from ribhus.tools.clarify import ClarifyTool
from ribhus.tools.registry import default_registry


@pytest.mark.asyncio
async def test_clarify_without_asker_preflight():
    tool = ClarifyTool(asker=None)
    blocked = tool.preflight({"question": "Budget?"})
    assert blocked is not None
    assert "interactive" in blocked.lower() or "CLI" in blocked


@pytest.mark.asyncio
async def test_clarify_with_choices():
    answers: list[str] = []

    def asker(question: str, choices: list[str] | None) -> str:
        answers.append(question)
        assert choices == ["₹5,000", "₹8,000"]
        return "2"

    tool = ClarifyTool(asker=asker)
    result = await tool.execute(
        {
            "question": "What's your hotel budget per night?",
            "choices": ["₹5,000", "₹8,000"],
        }
    )
    assert result == "User answered: ₹8,000"
    assert answers


@pytest.mark.asyncio
async def test_clarify_cancel():
    tool = ClarifyTool(asker=lambda q, c: "cancel")
    result = await tool.execute({"question": "Which city?"})
    assert "skipped" in result.lower() or "assumption" in result.lower()


@pytest.mark.asyncio
async def test_clarify_free_text():
    tool = ClarifyTool(asker=lambda q, c: "Bengaluru")
    result = await tool.execute({"question": "Which city?"})
    assert result == "User answered: Bengaluru"


def test_default_registry_includes_clarify(tmp_path):
    assert "clarify" in default_registry(tmp_path).names()


def test_default_registry_wires_asker(tmp_path):
    tool = default_registry(
        tmp_path, clarify_asker=lambda q, c: "ok"
    ).get("clarify")
    assert tool is not None
    assert tool.asker is not None
