"""message_bot — async handoff to another bot."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ribhus.policy.levels import RiskLevel
from ribhus.tools.base import Tool

MAX_HANDOFF_HOPS = 3


class MessageBotTool(Tool):
    name = "message_bot"
    description = (
        "Send an asynchronous message to another bot on this roster. "
        "Returns immediately after queueing — do not wait for their reply. "
        "Use priority=action when they should do work and reply; "
        "priority=fyi for a note that needs no reply. "
        "Do not message the same bot back about the same handoff."
    )
    risk_level = RiskLevel.LOW.value

    def __init__(
        self,
        *,
        sender_bot_id: str,
        sender_chat_id: str,
        hop: int,
        enqueue: Callable[[dict[str, Any]], str],
        list_bots: Callable[[], list[dict[str, str]]],
    ) -> None:
        self.sender_bot_id = sender_bot_id
        self.sender_chat_id = sender_chat_id
        self.hop = hop
        self._enqueue = enqueue
        self._list_bots = list_bots

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Bot name or id to message",
                },
                "body": {
                    "type": "string",
                    "description": "What the other bot should know or do",
                },
                "priority": {
                    "type": "string",
                    "enum": ["action", "fyi"],
                    "description": "action = do work and reply; fyi = no reply expected",
                },
            },
            "required": ["to", "body"],
        }

    async def execute(self, arguments: dict[str, Any]) -> str:
        if self.hop >= MAX_HANDOFF_HOPS:
            return (
                f"Error: handoff hop limit ({MAX_HANDOFF_HOPS}) reached. "
                "Finish the work yourself or ask the user."
            )
        to_raw = str(arguments.get("to") or "").strip()
        body = str(arguments.get("body") or "").strip()
        priority = str(arguments.get("priority") or "action").strip().lower()
        if priority not in {"action", "fyi"}:
            priority = "action"
        if not to_raw:
            return "Error: to is required"
        if not body:
            return "Error: body is required"

        bots = self._list_bots()
        target = None
        needle = to_raw.lower()
        for bot in bots:
            if bot["id"] == to_raw or bot["name"].lower() == needle:
                target = bot
                break
        if target is None:
            names = ", ".join(b["name"] for b in bots) or "(none)"
            return f"Error: no bot named {to_raw!r}. Available: {names}"
        if target["id"] == self.sender_bot_id:
            return "Error: cannot message yourself"

        result = self._enqueue(
            {
                "to_bot_id": target["id"],
                "to_name": target["name"],
                "body": body,
                "priority": priority,
                "from_bot_id": self.sender_bot_id,
                "from_chat_id": self.sender_chat_id,
                "hop": self.hop + 1,
            }
        )
        return result
