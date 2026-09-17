from __future__ import annotations

from typing import Any

import pytest

from ribhus.agent.loop import Agent
from ribhus.models.base import ModelResponse, ToolCall
from ribhus.tools.base import Tool
from ribhus.tools.registry import ToolRegistry


class FakeModel:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = list(responses)
        self.calls = 0

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelResponse:
        self.calls += 1
        if not self.responses:
            return ModelResponse(text="fallback")
        return self.responses.pop(0)


class EchoTool(Tool):
    name = "echo"
    description = "Echo text"
    risk_level = "low"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

    async def execute(self, arguments: dict[str, Any]) -> str:
        return str(arguments.get("text", ""))


class FakeRawMessage:
    def __init__(self, content: str | None, tool_calls: list | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class FakeFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class FakeToolCallObj:
    def __init__(self, id: str, name: str, arguments: str) -> None:
        self.id = id
        self.function = FakeFunction(name, arguments)


@pytest.mark.asyncio
async def test_agent_loop_tool_then_finish():
    registry = ToolRegistry()
    registry.register(EchoTool())

    raw_tool = FakeRawMessage(
        content=None,
        tool_calls=[FakeToolCallObj("call_1", "echo", '{"text": "hi"}')],
    )
    raw_final = FakeRawMessage(content="All done: hi", tool_calls=None)

    model = FakeModel(
        [
            ModelResponse(
                text=None,
                tool_calls=[ToolCall(id="call_1", name="echo", arguments={"text": "hi"})],
                raw=raw_tool,
            ),
            ModelResponse(text="All done: hi", tool_calls=[], raw=raw_final),
        ]
    )

    agent = Agent(model=model, tools=registry, max_iterations=5)  # type: ignore[arg-type]
    state = await agent.run("say hi")

    assert state.finished
    assert state.final_text == "All done: hi"
    assert model.calls == 2
    assert any(m.get("role") == "tool" for m in state.messages)


@pytest.mark.asyncio
async def test_agent_breaks_repeated_tool_calls():
    registry = ToolRegistry()
    registry.register(EchoTool())

    def tool_response() -> ModelResponse:
        raw = FakeRawMessage(
            content=None,
            tool_calls=[FakeToolCallObj("c1", "echo", '{"text": "hi"}')],
        )
        return ModelResponse(
            text=None,
            tool_calls=[ToolCall(id="c1", name="echo", arguments={"text": "hi"})],
            raw=raw,
        )

    model = FakeModel(
        [
            tool_response(),
            tool_response(),  # identical → stuck detection
            ModelResponse(
                text="Answer after stuck loop",
                tool_calls=[],
                raw=FakeRawMessage("Answer after stuck loop"),
            ),
        ]
    )
    agent = Agent(model=model, tools=registry, max_iterations=8)  # type: ignore[arg-type]
    state = await agent.run("loop")

    assert state.finished
    assert "Answer after stuck loop" in (state.final_text or "")
    assert model.calls == 3
