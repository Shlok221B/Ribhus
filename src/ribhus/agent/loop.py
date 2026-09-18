from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from ribhus.agent.state import SYSTEM_PROMPT, AgentState
from ribhus.memory.service import MemoryService
from ribhus.models.base import ModelResponse, ToolCall
from ribhus.models.openai_compatible import OpenAICompatibleModel
from ribhus.tools.registry import ToolRegistry

ToolEventCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]


def _tools_used(state: AgentState) -> list[str]:
    names: list[str] = []
    for message in state.messages:
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            fn = call.get("function")
            if isinstance(fn, dict) and fn.get("name"):
                names.append(str(fn["name"]))
    return names


def _call_signature(call: ToolCall) -> str:
    try:
        args = json.dumps(call.arguments, sort_keys=True, default=str)
    except TypeError:
        args = str(call.arguments)
    return f"{call.name}:{args}"


class Agent:
    def __init__(
        self,
        model: OpenAICompatibleModel,
        tools: ToolRegistry,
        *,
        max_iterations: int = 12,
        system_prompt: str = SYSTEM_PROMPT,
        on_event: ToolEventCallback | None = None,
        skill_prompt_addon: str = "",
        skill_names: list[str] | None = None,
        memory: MemoryService | None = None,
    ) -> None:
        self.model = model
        self.tools = tools
        self.max_iterations = max_iterations
        self.system_prompt = system_prompt
        self.on_event = on_event
        self.skill_prompt_addon = skill_prompt_addon
        self.skill_names = skill_names or []
        self.memory = memory

    async def _emit(self, event: str, data: dict[str, Any] | None = None) -> None:
        if self.on_event is None:
            return
        result = self.on_event(event, data or {})
        if result is not None:
            await result

    def _append_assistant(self, state: AgentState, response: ModelResponse) -> None:
        if response.raw is not None:
            state.add_assistant_message(response.raw)
            return
        if response.has_tool_calls():
            state.messages.append(
                {
                    "role": "assistant",
                    "content": response.text,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments),
                            },
                        }
                        for call in response.tool_calls
                    ],
                }
            )
            return
        state.messages.append({"role": "assistant", "content": response.text or ""})

    async def _final_answer(self, state: AgentState, reason: str) -> None:
        """Force a text-only completion so the user gets a real answer."""
        state.messages.append(
            {
                "role": "user",
                "content": (
                    f"{reason} Do not call any tools. "
                    "Give your best final answer now based on the information so far."
                ),
            }
        )
        await self._emit("thinking", {"iteration": state.iterations, "final": True})
        response = await self.model.generate(messages=state.messages, tools=None)
        self._append_assistant(state, response)
        text = (response.text or "").strip()
        if not text:
            text = (
                f"Stopped ({reason.lower()}). "
                "No final summary was produced — try a simpler prompt."
            )
        state.finish(text)
        await self._emit("done", {"text": state.final_text or ""})

    def _persist_run(self, prompt: str, state: AgentState) -> None:
        if self.memory is None or not state.finished:
            return
        outcome = state.final_text or ""
        self.memory.record_episode(
            prompt,
            outcome,
            skills=self.skill_names or None,
            tools=_tools_used(state) or None,
        )
        self.memory.set_short_term(prompt, outcome)
        self.memory.extract_and_persist(prompt, outcome)

    async def run(self, prompt: str) -> AgentState:
        state = AgentState()
        memory_addon = ""
        if self.memory is not None and self.memory.enabled:
            if hasattr(self.memory, "prepare_for_prompt"):
                self.memory.prepare_for_prompt(
                    prompt, skill_names=self.skill_names or None
                )
            memory_addon = self.memory.prompt_addon(prompt)
        system = self.system_prompt + memory_addon + (self.skill_prompt_addon or "")
        state.add_system(system)
        state.add_user(prompt)

        if self.skill_prompt_addon and "Active skills" in self.skill_prompt_addon:
            await self._emit("skill", {"addon_preview": self.skill_prompt_addon[:200]})

        recent_signatures: list[str] = []
        force_text_only = False

        while not state.finished:
            if state.iterations >= self.max_iterations:
                await self._final_answer(
                    state,
                    f"Reached the maximum of {self.max_iterations} tool steps.",
                )
                break

            state.iterations += 1
            await self._emit("thinking", {"iteration": state.iterations})

            tools = None if force_text_only else self.tools.schemas()
            response: ModelResponse = await self.model.generate(
                messages=state.messages,
                tools=tools,
            )
            self._append_assistant(state, response)

            if force_text_only or not response.has_tool_calls():
                state.finish(response.text)
                await self._emit("done", {"text": state.final_text or ""})
                break

            signatures = [_call_signature(call) for call in response.tool_calls]
            if signatures and recent_signatures == signatures:
                for call in response.tool_calls:
                    note = (
                        "Repeated identical tool call detected. "
                        "Result unchanged — stop retrying and answer the user."
                    )
                    state.add_tool_result(call.id, note)
                force_text_only = True
                continue

            recent_signatures = signatures

            for call in response.tool_calls:
                await self._emit(
                    "tool_start",
                    {"name": call.name, "arguments": call.arguments},
                )
                result = await self.tools.execute(call.name, call.arguments)
                await self._emit(
                    "tool_end",
                    {"name": call.name, "result_preview": result[:500]},
                )
                state.add_tool_result(call.id, result)

        self._persist_run(prompt, state)
        return state
