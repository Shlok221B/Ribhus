from __future__ import annotations

from typing import Any

import pytest

from ribhus.agent.loop import Agent
from ribhus.models.base import ModelResponse, ToolCall
from ribhus.skills.travel_handoff import looks_travel_handoff
from ribhus.tools.base import Tool
from ribhus.tools.registry import ToolRegistry


def test_looks_travel_handoff():
    assert looks_travel_handoff("2")
    assert looks_travel_handoff("option 1")
    assert looks_travel_handoff("go with 3")
    assert looks_travel_handoff("open payment page")
    assert looks_travel_handoff("finalize the first one")
    assert not looks_travel_handoff("Find me a hotel in Goa")
    assert not looks_travel_handoff("")


def test_sticky_travel_on_selection():
    from pathlib import Path

    from ribhus.skills.loader import load_skill
    from ribhus.skills.registry import SkillRegistry

    travel = load_skill(
        Path(__file__).resolve().parents[1]
        / "src"
        / "ribhus"
        / "skills"
        / "bundled"
        / "travel"
    )
    registry = SkillRegistry([travel])
    assert registry.match("2") == []
    sticky = registry.match_with_sticky("2", ["travel"])
    assert len(sticky) == 1
    assert sticky[0].name == "travel"
    addon = registry.prompt_addon("2", sticky_names=["travel"])
    assert "Active skills" in addon
    assert "Phase B" in addon


class BrowserStub(Tool):
    name = "browser"
    description = "browser"
    risk_level = "medium"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"action": {"type": "string"}}}

    async def execute(self, arguments: dict[str, Any]) -> str:
        self.calls.append(arguments)
        return "Opened https://example.com/book\nTitle: Checkout"


class FakeModel:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = list(responses)
        self.calls = 0

    async def generate(self, messages, tools=None):
        self.calls += 1
        if not self.responses:
            return ModelResponse(text="fallback")
        return self.responses.pop(0)


class FakeRaw:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class FakeFn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class FakeTC:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = FakeFn(name, arguments)


@pytest.mark.asyncio
async def test_travel_handoff_nudge_forces_browser():
    refuse = (
        "I can't complete the booking myself. However, you can proceed "
        "with the booking through the provided links."
    )
    browser = BrowserStub()
    registry = ToolRegistry()
    registry.register(browser)

    model = FakeModel(
        [
            ModelResponse(text=refuse, tool_calls=[], raw=FakeRaw(refuse)),
            ModelResponse(
                text=None,
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="browser",
                        arguments={
                            "action": "open",
                            "url": "https://example.com/book",
                        },
                    )
                ],
                raw=FakeRaw(
                    None,
                    [
                        FakeTC(
                            "c1",
                            "browser",
                            '{"action":"open","url":"https://example.com/book"}',
                        )
                    ],
                ),
            ),
            ModelResponse(
                text="Browser is on the payment page — please pay there.",
                tool_calls=[],
                raw=FakeRaw("Browser is on the payment page — please pay there."),
            ),
        ]
    )
    agent = Agent(
        model=model,  # type: ignore[arg-type]
        tools=registry,
        max_iterations=8,
        skill_names=["travel"],
        skill_prompt_addon="## Active skills (travel)\nPhase B handoff",
    )
    history = [
        {"role": "user", "content": "Find hotel in Goa"},
        {
            "role": "assistant",
            "content": (
                "## Shortlist\n1. **Sea View** — ₹5k\n"
                "Source: https://example.com/book\n"
                "Reply with 1, 2, or 3"
            ),
        },
    ]
    state = await agent.run("2", history=history)
    assert browser.calls, "browser tool should have been called after nudge"
    assert "payment" in (state.final_text or "").lower() or state.finished
    assert model.calls >= 3
