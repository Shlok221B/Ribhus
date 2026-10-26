from __future__ import annotations

from ribhus.agent.loop import Agent
from ribhus.agent.plan_loop import PLAN_NUDGE, looks_multi_step
from ribhus.eval.harness import EchoTool, FakeModel, text_response, tool_response, user_contents
from ribhus.eval.models import EvalCase
from ribhus.skills.travel_handoff import TRAVEL_HANDOFF_NUDGE, looks_travel_handoff
from ribhus.tools.base import Tool
from ribhus.tools.registry import ToolRegistry
from ribhus.tools.todo import TodoStore, TodoTool


async def tool_then_finish() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())
    model = FakeModel(
        [
            tool_response("c1", "echo", {"text": "hi"}),
            text_response("All done: hi"),
        ]
    )
    agent = Agent(model=model, tools=registry, max_iterations=5)  # type: ignore[arg-type]
    state = await agent.run("say hi")
    assert state.finished
    assert state.final_text == "All done: hi"
    assert model.calls == 2
    assert any(m.get("role") == "tool" for m in state.messages)


async def unknown_tool_error() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())
    model = FakeModel(
        [
            tool_response("c1", "nope", {}),
            text_response("I could not find that tool."),
        ]
    )
    agent = Agent(model=model, tools=registry, max_iterations=5)  # type: ignore[arg-type]
    state = await agent.run("use missing tool")
    tool_msgs = [m.get("content") or "" for m in state.messages if m.get("role") == "tool"]
    assert any("unknown tool" in str(msg) for msg in tool_msgs)
    assert state.finished


async def stuck_loop_breaks() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())
    model = FakeModel(
        [
            tool_response("c1", "echo", {"text": "hi"}),
            tool_response("c1", "echo", {"text": "hi"}),
            text_response("Answer after stuck loop"),
        ]
    )
    agent = Agent(model=model, tools=registry, max_iterations=8)  # type: ignore[arg-type]
    state = await agent.run("loop")
    assert state.finished
    assert "Answer after stuck loop" in (state.final_text or "")
    assert model.calls == 3


async def plan_nudge_multi_step() -> None:
    prompt = (
        "Research top cafes in Goa then draft and send an email summary to a@b.com"
    )
    assert looks_multi_step(prompt)
    store = TodoStore()
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(TodoTool(store=store))
    model = FakeModel(
        [
            tool_response("c1", "echo", {"text": "cafes"}),
            tool_response("c2", "echo", {"text": "ok"}),
            text_response("Finished after plan nudge."),
        ]
    )
    agent = Agent(
        model=model,  # type: ignore[arg-type]
        tools=registry,
        max_iterations=8,
        todo_store=store,
    )
    state = await agent.run(prompt)
    assert state.finished
    assert any(PLAN_NUDGE in c for c in user_contents(state))
    assert any(
        "Skipped: plan required" in str(m.get("content") or "")
        for m in state.messages
        if m.get("role") == "tool"
    )


class _BrowserStub(Tool):
    name = "browser"
    description = "browser"
    risk_level = "medium"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def input_schema(self) -> dict:
        return {"type": "object", "properties": {"action": {"type": "string"}}}

    async def execute(self, arguments: dict) -> str:
        self.calls.append(arguments)
        return "Opened https://example.com/book\nTitle: Checkout"


async def travel_handoff_nudge() -> None:
    assert looks_travel_handoff("2")
    browser = _BrowserStub()
    registry = ToolRegistry()
    registry.register(browser)
    refuse = "I can't complete the booking myself. Use the provided links."
    model = FakeModel(
        [
            text_response(refuse),
            tool_response(
                "c1",
                "browser",
                {"action": "open", "url": "https://example.com/book"},
            ),
            text_response("Browser is on the payment page — please pay there."),
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
    assert any(TRAVEL_HANDOFF_NUDGE in c for c in user_contents(state))
    assert browser.calls
    assert state.finished


CASES = [
    EvalCase("agentic-tool-finish", "agentic", "agent.loop", "Tool then final answer", tool_then_finish),
    EvalCase("agentic-unknown-tool", "agentic", "agent.loop", "Unknown tool error observation", unknown_tool_error),
    EvalCase("agentic-stuck-loop", "agentic", "agent.loop", "Repeated tool calls break", stuck_loop_breaks),
    EvalCase("agentic-plan-nudge", "agentic", "plan_loop", "Multi-step prompt gets todo nudge", plan_nudge_multi_step),
    EvalCase("agentic-travel-handoff", "agentic", "travel_handoff", "Finalize injects browser nudge", travel_handoff_nudge),
]
