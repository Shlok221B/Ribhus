from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from ribhus.agent.plan_loop import (
    CONSEQUENTIAL_TOOLS,
    PLAN_INCOMPLETE_NUDGE,
    PLAN_NUDGE,
    VERIFY_NUDGE,
    batch_has_non_todo,
    batch_writes_plan,
    looks_multi_step,
    plan_has_open_items,
    plan_summary,
)
from ribhus.agent.state import SYSTEM_PROMPT, AgentState
from ribhus.memory.service import MemoryService
from ribhus.models.base import ModelResponse, ToolCall
from ribhus.models.openai_compatible import OpenAICompatibleModel
from ribhus.tools.registry import ToolRegistry
from ribhus.tools.todo import TodoStore

ToolEventCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]

_MAX_HISTORY_MESSAGES = 48

_CHAT_APPROVAL_RE = re.compile(
    r"(need your (explicit )?approval|"
    r"would you like me to (proceed|send|continue)|"
    r"may i (send|proceed)|"
    r"shall i send|"
    r"please (approve|confirm)|"
    r"(do you want me to|should i) send|"
    r"permission to send|"
    r"awaiting (your )?approval)",
    re.IGNORECASE,
)

_EMAIL_GIVE_UP_RE = re.compile(
    r"(unable to send|"
    r"can'?t send|"
    r"cannot send|"
    r"usual method|"
    r"send(ing)? the email directly|"
    r"through your gmail|"
    r"try sending.*(yourself|manually|directly)|"
    r"please try sending|"
    r"send it (yourself|manually))",
    re.IGNORECASE,
)


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


def _tool_result_ok(result: str) -> bool:
    text = (result or "").strip()
    if not text:
        return False
    lower = text.lower()
    if text.startswith("Error"):
        return False
    if "user denied" in lower or "user cancelled" in lower or "denied/cancelled" in lower:
        return False
    if lower.startswith("denied ") or " denied " in lower:
        return False
    return True


def asks_send_approval_in_chat(text: str | None) -> bool:
    return bool(_CHAT_APPROVAL_RE.search(text or ""))


def gives_up_on_email_send(text: str | None) -> bool:
    return bool(_EMAIL_GIVE_UP_RE.search(text or ""))


def _trim_history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(messages) <= _MAX_HISTORY_MESSAGES:
        return messages
    trimmed = messages[-_MAX_HISTORY_MESSAGES:]
    # Avoid starting mid tool-call exchange.
    while trimmed and trimmed[0].get("role") == "tool":
        trimmed = trimmed[1:]
    return trimmed


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
        todo_store: TodoStore | None = None,
    ) -> None:
        self.model = model
        self.tools = tools
        self.max_iterations = max_iterations
        self.system_prompt = system_prompt
        self.on_event = on_event
        self.skill_prompt_addon = skill_prompt_addon
        self.skill_names = skill_names or []
        self.memory = memory
        self.todo_store = todo_store

    def _resolve_todo_store(self) -> TodoStore | None:
        if self.todo_store is not None:
            return self.todo_store
        tool = self.tools.get("todo")
        store = getattr(tool, "store", None) if tool is not None else None
        return store if isinstance(store, TodoStore) else None

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

    def _should_nudge_send_tool(self, text: str | None) -> bool:
        if self.tools.get("email_send") is None and self.tools.get("whatsapp_send") is None:
            return False
        if asks_send_approval_in_chat(text):
            return True
        if self.tools.get("email_send") is not None and gives_up_on_email_send(text):
            return True
        return False

    def _inject_user(self, state: AgentState, content: str) -> None:
        state.messages.append({"role": "user", "content": content})

    async def run(
        self,
        prompt: str,
        *,
        history: list[dict[str, Any]] | None = None,
    ) -> AgentState:
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
        if history:
            state.messages.extend(_trim_history(list(history)))
        state.add_user(prompt)

        if self.skill_prompt_addon and "Active skills" in self.skill_prompt_addon:
            await self._emit("skill", {"addon_preview": self.skill_prompt_addon[:200]})

        todo_store = self._resolve_todo_store()
        require_plan = looks_multi_step(prompt) and self.tools.get("todo") is not None
        recent_signatures: list[str] = []
        force_text_only = False
        approval_nudge_used = False
        whatsapp_path_nudge_used = False
        plan_nudge_used = False
        plan_incomplete_nudge_used = False
        verify_nudge_used = False
        consequential_ok = False

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
                if (
                    not force_text_only
                    and not approval_nudge_used
                    and self._should_nudge_send_tool(response.text)
                ):
                    approval_nudge_used = True
                    self._inject_user(
                        state,
                        (
                            "STOP. Do not ask for chat approval and do not tell "
                            "the user to send email themselves. "
                            "Call email_send now with mode=new, to, subject, and body "
                            "taken from the user's request (or whatsapp_send if that "
                            "was the task). The CLI will show Approve/Edit/Cancel. "
                            "If the tool returns Error, quote that exact error."
                        ),
                    )
                    continue

                # Plan incomplete gate
                if (
                    not force_text_only
                    and not plan_incomplete_nudge_used
                    and plan_has_open_items(todo_store)
                ):
                    plan_incomplete_nudge_used = True
                    self._inject_user(state, PLAN_INCOMPLETE_NUDGE)
                    continue

                # Verify gate after consequential successes
                if (
                    not force_text_only
                    and consequential_ok
                    and not verify_nudge_used
                ):
                    verify_nudge_used = True
                    self._inject_user(state, VERIFY_NUDGE)
                    continue

                state.finish(response.text)
                await self._emit("done", {"text": state.final_text or ""})
                break

            # Plan gate: multi-step + empty store + non-todo tools first
            if (
                require_plan
                and not plan_nudge_used
                and todo_store is not None
                and not todo_store.has_items()
                and batch_has_non_todo(response.tool_calls)
                and not batch_writes_plan(response.tool_calls)
            ):
                plan_nudge_used = True
                for call in response.tool_calls:
                    state.add_tool_result(
                        call.id,
                        "Skipped: plan required before other tools. " + PLAN_NUDGE,
                    )
                self._inject_user(state, PLAN_NUDGE)
                continue

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

            results: list[str] = []
            for call in response.tool_calls:
                await self._emit(
                    "tool_start",
                    {"name": call.name, "arguments": call.arguments},
                )
                result = await self.tools.execute(call.name, call.arguments)
                results.append(result)
                ok = _tool_result_ok(result)
                if call.name in CONSEQUENTIAL_TOOLS and ok:
                    consequential_ok = True
                await self._emit(
                    "tool_end",
                    {
                        "name": call.name,
                        "result_preview": result[:500],
                        "ok": ok,
                    },
                )
                state.add_tool_result(call.id, result)

            if any(call.name == "todo" for call in response.tool_calls):
                summary = plan_summary(todo_store)
                if summary is not None:
                    await self._emit("plan", summary)

            # Soft nudge: prefer whatsapp_reply over open_chat (+ optional read).
            tool_names = {call.name for call in response.tool_calls}
            if (
                not whatsapp_path_nudge_used
                and self.tools.get("whatsapp_reply") is not None
                and "whatsapp_open_chat" in tool_names
                and "whatsapp_reply" not in tool_names
                and "whatsapp_send" not in tool_names
            ):
                whatsapp_path_nudge_used = True
                self._inject_user(
                    state,
                    (
                        "Prefer `whatsapp_reply` (open+read in one call) for "
                        "WhatsApp replies. If the chat is already open from "
                        "whatsapp_open_chat, call whatsapp_read without re-opening, "
                        "draft, then whatsapp_send — or use whatsapp_reply next time."
                    ),
                )

            # Only treat as a repeat candidate when every call actually succeeded.
            # Cancelled/denied sends must be retryable with the same arguments.
            if results and all(_tool_result_ok(r) for r in results):
                recent_signatures = signatures
            else:
                recent_signatures = []

        self._persist_run(prompt, state)
        return state
