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


class EmailSendStub(Tool):
    name = "email_send"
    description = "Send email"
    risk_level = "high"

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"body": {"type": "string"}}}

    async def execute(self, arguments: dict[str, Any]) -> str:
        return f"Sent: {arguments.get('body')}"


@pytest.mark.asyncio
async def test_chat_approval_nudge_forces_email_send():
    from ribhus.agent.loop import asks_send_approval_in_chat, gives_up_on_email_send

    assert asks_send_approval_in_chat(
        "I need your explicit approval to send the email. Would you like me to proceed?"
    )
    assert gives_up_on_email_send(
        "I'm currently unable to send emails through the usual method. "
        "Please try sending the email directly through your Gmail account."
    )

    registry = ToolRegistry()
    registry.register(EmailSendStub())

    ask = (
        "I need your explicit approval to send the email to a@b.com. "
        "Would you like me to proceed?"
    )
    model = FakeModel(
        [
            ModelResponse(text=ask, tool_calls=[], raw=FakeRawMessage(ask)),
            ModelResponse(
                text=None,
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="email_send",
                        arguments={"body": "pending tasks update"},
                    )
                ],
                raw=FakeRawMessage(
                    None,
                    [FakeToolCallObj("c1", "email_send", '{"body":"pending tasks update"}')],
                ),
            ),
            ModelResponse(
                text="Sent after CLI approval.",
                tool_calls=[],
                raw=FakeRawMessage("Sent after CLI approval."),
            ),
        ]
    )
    agent = Agent(model=model, tools=registry, max_iterations=5)  # type: ignore[arg-type]
    state = await agent.run("send email about pending tasks")

    assert state.finished
    assert "Sent after CLI approval" in (state.final_text or "")
    assert any(m.get("role") == "tool" for m in state.messages)
    assert model.calls == 3


@pytest.mark.asyncio
async def test_email_give_up_nudge_forces_email_send():
    registry = ToolRegistry()
    registry.register(EmailSendStub())

    give_up = (
        "I'm currently unable to send emails through the usual method. "
        "Please try sending the email directly through your Gmail account."
    )
    model = FakeModel(
        [
            ModelResponse(text=give_up, tool_calls=[], raw=FakeRawMessage(give_up)),
            ModelResponse(
                text=None,
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="email_send",
                        arguments={"body": "hi", "to": "a@b.com", "subject": "x"},
                    )
                ],
                raw=FakeRawMessage(
                    None,
                    [
                        FakeToolCallObj(
                            "c1",
                            "email_send",
                            '{"body":"hi","to":"a@b.com","subject":"x"}',
                        )
                    ],
                ),
            ),
            ModelResponse(
                text="Sent.",
                tool_calls=[],
                raw=FakeRawMessage("Sent."),
            ),
        ]
    )
    agent = Agent(model=model, tools=registry, max_iterations=5)  # type: ignore[arg-type]
    state = await agent.run("send email to a@b.com")
    assert state.final_text == "Sent."
    assert model.calls == 3


@pytest.mark.asyncio
async def test_run_with_history_continues_conversation():
    registry = ToolRegistry()
    registry.register(EmailSendStub())

    history = [
        {"role": "user", "content": "send email to a@b.com about tasks"},
        {
            "role": "assistant",
            "content": "I need your explicit approval to send. Proceed?",
        },
    ]
    model = FakeModel(
        [
            ModelResponse(
                text=None,
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="email_send",
                        arguments={"to": "a@b.com", "body": "tasks"},
                    )
                ],
                raw=FakeRawMessage(
                    None,
                    [
                        FakeToolCallObj(
                            "c1",
                            "email_send",
                            '{"to":"a@b.com","body":"tasks"}',
                        )
                    ],
                ),
            ),
            ModelResponse(
                text="Email sent.",
                tool_calls=[],
                raw=FakeRawMessage("Email sent."),
            ),
        ]
    )
    agent = Agent(model=model, tools=registry, max_iterations=5)  # type: ignore[arg-type]
    state = await agent.run("y", history=history)

    assert state.finished
    assert state.final_text == "Email sent."
    roles = [m.get("role") for m in state.messages]
    assert roles.count("user") >= 2
    hist = state.history_messages()
    assert all(m.get("role") != "system" for m in hist)
