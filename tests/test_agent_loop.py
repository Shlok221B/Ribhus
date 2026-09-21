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
    assert model.calls == 4


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
    assert model.calls == 4


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


def _user_contents(state) -> list[str]:
    return [
        str(m.get("content") or "")
        for m in state.messages
        if m.get("role") == "user"
    ]


@pytest.mark.asyncio
async def test_plan_nudge_when_multi_step_skips_todo():
    from ribhus.agent.plan_loop import PLAN_NUDGE
    from ribhus.tools.todo import TodoStore, TodoTool

    store = TodoStore()
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(TodoTool(store=store))

    prompt = (
        "Research top cafes in Goa then draft and send an email summary to a@b.com"
    )
    model = FakeModel(
        [
            ModelResponse(
                text=None,
                tool_calls=[
                    ToolCall(id="c1", name="echo", arguments={"text": "cafes"})
                ],
                raw=FakeRawMessage(
                    None,
                    [FakeToolCallObj("c1", "echo", '{"text":"cafes"}')],
                ),
            ),
            ModelResponse(
                text=None,
                tool_calls=[
                    ToolCall(id="c2", name="echo", arguments={"text": "ok"})
                ],
                raw=FakeRawMessage(
                    None,
                    [FakeToolCallObj("c2", "echo", '{"text":"ok"}')],
                ),
            ),
            ModelResponse(
                text="Finished after plan nudge.",
                tool_calls=[],
                raw=FakeRawMessage("Finished after plan nudge."),
            ),
        ]
    )
    events: list[str] = []

    async def on_event(event: str, data: dict) -> None:
        events.append(event)

    agent = Agent(
        model=model,  # type: ignore[arg-type]
        tools=registry,
        max_iterations=8,
        todo_store=store,
        on_event=on_event,
    )
    state = await agent.run(prompt)

    assert state.finished
    assert any(PLAN_NUDGE in c for c in _user_contents(state))
    assert any(
        "Skipped: plan required" in str(m.get("content") or "")
        for m in state.messages
        if m.get("role") == "tool"
    )
    # Second echo was allowed to execute (nudge only once).
    assert any(
        m.get("role") == "tool" and m.get("content") == "ok" for m in state.messages
    )
    assert state.final_text == "Finished after plan nudge."


@pytest.mark.asyncio
async def test_incomplete_todos_block_finish_once():
    from ribhus.agent.plan_loop import PLAN_INCOMPLETE_NUDGE
    from ribhus.tools.todo import TodoStore, TodoTool

    store = TodoStore()
    store.write(
        [
            {"id": "1", "content": "research", "status": "in_progress"},
            {"id": "2", "content": "send", "status": "pending"},
        ],
        merge=False,
    )
    registry = ToolRegistry()
    registry.register(TodoTool(store=store))

    model = FakeModel(
        [
            ModelResponse(
                text="All done early.",
                tool_calls=[],
                raw=FakeRawMessage("All done early."),
            ),
            ModelResponse(
                text=None,
                tool_calls=[
                    ToolCall(
                        id="t1",
                        name="todo",
                        arguments={
                            "merge": True,
                            "todos": [
                                {
                                    "id": "1",
                                    "content": "research",
                                    "status": "completed",
                                },
                                {
                                    "id": "2",
                                    "content": "send",
                                    "status": "completed",
                                },
                            ],
                        },
                    )
                ],
                raw=FakeRawMessage(
                    None,
                    [
                        FakeToolCallObj(
                            "t1",
                            "todo",
                            '{"merge":true,"todos":[{"id":"1","content":"research","status":"completed"},{"id":"2","content":"send","status":"completed"}]}',
                        )
                    ],
                ),
            ),
            ModelResponse(
                text="Really finished.",
                tool_calls=[],
                raw=FakeRawMessage("Really finished."),
            ),
        ]
    )
    plan_events: list[dict] = []

    async def on_event(event: str, data: dict) -> None:
        if event == "plan":
            plan_events.append(data)

    agent = Agent(
        model=model,  # type: ignore[arg-type]
        tools=registry,
        max_iterations=8,
        todo_store=store,
        on_event=on_event,
    )
    state = await agent.run("what is 2+2")  # simple so plan gate stays off

    assert state.finished
    assert any(PLAN_INCOMPLETE_NUDGE in c for c in _user_contents(state))
    assert state.final_text == "Really finished."
    assert not any(
        i["status"] in {"pending", "in_progress"} for i in store.read()
    )
    assert plan_events


@pytest.mark.asyncio
async def test_verify_nudge_after_consequential_success():
    from ribhus.agent.plan_loop import VERIFY_NUDGE

    registry = ToolRegistry()
    registry.register(EmailSendStub())

    model = FakeModel(
        [
            ModelResponse(
                text=None,
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="email_send",
                        arguments={"body": "hi", "to": "a@b.com"},
                    )
                ],
                raw=FakeRawMessage(
                    None,
                    [
                        FakeToolCallObj(
                            "c1",
                            "email_send",
                            '{"body":"hi","to":"a@b.com"}',
                        )
                    ],
                ),
            ),
            ModelResponse(
                text="Email is out.",
                tool_calls=[],
                raw=FakeRawMessage("Email is out."),
            ),
            ModelResponse(
                text="Verified: Sent: hi",
                tool_calls=[],
                raw=FakeRawMessage("Verified: Sent: hi"),
            ),
        ]
    )
    agent = Agent(model=model, tools=registry, max_iterations=8)  # type: ignore[arg-type]
    state = await agent.run("send a short email")

    assert state.finished
    assert any(VERIFY_NUDGE in c for c in _user_contents(state))
    assert state.final_text == "Verified: Sent: hi"
    assert model.calls == 3


@pytest.mark.asyncio
async def test_simple_prompt_skips_plan_and_verify_nudges():
    from ribhus.agent.plan_loop import (
        PLAN_INCOMPLETE_NUDGE,
        PLAN_NUDGE,
        VERIFY_NUDGE,
    )
    from ribhus.tools.todo import TodoStore, TodoTool

    store = TodoStore()
    registry = ToolRegistry()
    registry.register(TodoTool(store=store))
    registry.register(EchoTool())

    model = FakeModel(
        [
            ModelResponse(
                text="4",
                tool_calls=[],
                raw=FakeRawMessage("4"),
            ),
        ]
    )
    agent = Agent(
        model=model,  # type: ignore[arg-type]
        tools=registry,
        max_iterations=5,
        todo_store=store,
    )
    state = await agent.run("what is 2+2")

    assert state.finished
    assert state.final_text == "4"
    assert model.calls == 1
    joined = "\n".join(_user_contents(state))
    assert PLAN_NUDGE not in joined
    assert PLAN_INCOMPLETE_NUDGE not in joined
    assert VERIFY_NUDGE not in joined
