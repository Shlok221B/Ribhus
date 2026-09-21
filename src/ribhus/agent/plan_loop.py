"""Plan / verify helpers for the agent loop.

Reuses TodoStore as the plan. Multi-step work gets one plan nudge;
incomplete plans and consequential tool successes get one finish gate each.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ribhus.tools.todo import TodoStore

CONSEQUENTIAL_TOOLS = frozenset(
    {
        "email_send",
        "whatsapp_send",
        "write_file",
        "edit_file",
    }
)

_MULTI_STEP_CONNECTORS = re.compile(
    r"\b("
    r"then|and then|after that|afterwards|afterward|"
    r"first[, ]|next[, ]|finally|"
    r"followed by|as well as"
    r")\b",
    re.IGNORECASE,
)

_RESEARCH_THEN_ACT = re.compile(
    r"\b(research|find|search|look up|compare|shortlist)\b"
    r".{0,80}\b(whatsapp|email|gmail|send|message|draft|reply)\b"
    r"|"
    r"\b(whatsapp|email|gmail|send|message|draft|reply)\b"
    r".{0,80}\b(research|find|search|look up|compare|shortlist)\b",
    re.IGNORECASE | re.DOTALL,
)

_ACTION_VERBS = frozenset(
    {
        "research",
        "find",
        "search",
        "open",
        "read",
        "draft",
        "send",
        "write",
        "edit",
        "install",
        "create",
        "compare",
        "book",
        "check",
        "list",
        "summarize",
        "extract",
        "reply",
        "forward",
        "schedule",
    }
)

PLAN_NUDGE = (
    "PLAN FIRST. This looks multi-step. Call `todo` with merge=false and a short "
    "checklist (3–7 steps, one in_progress). Do not call other tools until the "
    "plan exists."
)

PLAN_INCOMPLETE_NUDGE = (
    "PLAN INCOMPLETE. The todo list still has pending or in_progress items. "
    "Either finish those steps with tools, or update `todo` (merge=true) to mark "
    "items completed/cancelled. Do not give the final answer yet."
)

VERIFY_NUDGE = (
    "VERIFY against the user goal before finishing. Quote concrete tool evidence "
    "(e.g. a result that starts with Sent… or a successful write). "
    "If the goal is unmet, call tools again. If it is met, give the final answer now."
)


def looks_multi_step(prompt: str) -> bool:
    """Heuristic: True when a todo plan should be nudged once."""
    text = (prompt or "").strip()
    if not text:
        return False
    if len(text) < 24 and " and " not in text.lower():
        return False
    if _MULTI_STEP_CONNECTORS.search(text):
        return True
    if _RESEARCH_THEN_ACT.search(text):
        return True

    lowered = text.lower()
    verbs = {v for v in _ACTION_VERBS if re.search(rf"\b{re.escape(v)}\b", lowered)}
    if len(verbs) >= 3:
        return True
    if len(text) >= 120 and " and " in lowered and len(verbs) >= 2:
        return True
    return False


def plan_has_open_items(store: TodoStore | None) -> bool:
    if store is None or not store.has_items():
        return False
    return any(
        item.get("status") in {"pending", "in_progress"} for item in store.read()
    )


def plan_summary(store: TodoStore | None) -> dict[str, object] | None:
    if store is None or not store.has_items():
        return None
    return {
        "summary": store.summary(),
        "display": store.format_display(),
    }


def batch_writes_plan(tool_calls: list) -> bool:
    """True if this tool batch includes a todo write (todos array present)."""
    for call in tool_calls:
        name = getattr(call, "name", None) or ""
        if name != "todo":
            continue
        args = getattr(call, "arguments", None) or {}
        if isinstance(args, dict) and args.get("todos") is not None:
            return True
    return False


def batch_has_non_todo(tool_calls: list) -> bool:
    return any(getattr(call, "name", None) != "todo" for call in tool_calls)
