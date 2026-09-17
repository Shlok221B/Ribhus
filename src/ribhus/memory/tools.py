from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ribhus.memory.service import MemoryService
from ribhus.policy.levels import RiskLevel
from ribhus.tools.base import Tool

if TYPE_CHECKING:
    from ribhus.tools.registry import ToolRegistry


class MemoryRememberTool(Tool):
    name = "memory_remember"
    description = (
        "Save a durable user preference or fact (semantic memory) that should "
        "survive across sessions. Do not store secrets, passwords, or API keys."
    )
    risk_level = RiskLevel.LOW.value

    def __init__(self, memory: MemoryService) -> None:
        self.memory = memory

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": "The preference or fact to remember",
                },
                "key": {
                    "type": "string",
                    "description": "Optional stable key to upsert (e.g. language)",
                },
            },
            "required": ["fact"],
        }

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        if not self.memory.enabled:
            return (
                "Error: memory is disabled. "
                "Enable with `ribhus memory enable` or RIBHUS_MEMORY_ENABLED=true."
            )
        return None

    async def execute(self, arguments: dict[str, Any]) -> str:
        fact = str(arguments.get("fact") or "").strip()
        if not fact:
            return "Error: fact is required"
        key = str(arguments.get("key") or "").strip() or None
        record = self.memory.remember_fact(fact, key=key)
        return f"Saved {record.id} ({record.kind}): {record.preview(120)}"


class MemoryRecallTool(Tool):
    name = "memory_recall"
    description = (
        "Search saved memories (preferences, past tasks). "
        "Use when the user refers to something from a previous session."
    )
    risk_level = RiskLevel.LOW.value

    def __init__(self, memory: MemoryService) -> None:
        self.memory = memory

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text to search in memories",
                },
            },
            "required": ["query"],
        }

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        if not self.memory.enabled:
            return (
                "Error: memory is disabled. "
                "Enable with `ribhus memory enable` or RIBHUS_MEMORY_ENABLED=true."
            )
        return None

    async def execute(self, arguments: dict[str, Any]) -> str:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return "Error: query is required"
        hits = self.memory.search(query)
        if not hits:
            return f"No memories matched {query!r}."
        lines = [f"- [{r.id}] ({r.kind}) {r.content}" for r in hits]
        return "Matching memories:\n" + "\n".join(lines)


def register_memory_tools(registry: ToolRegistry, memory: MemoryService) -> None:
    registry.register(MemoryRememberTool(memory))
    registry.register(MemoryRecallTool(memory))
