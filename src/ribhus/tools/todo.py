from __future__ import annotations

import json
from typing import Any

from ribhus.policy.levels import RiskLevel
from ribhus.tools.base import Tool

VALID_STATUSES = frozenset({"pending", "in_progress", "completed", "cancelled"})
_STATUS_MARKERS = {
    "completed": "[x]",
    "in_progress": "[>]",
    "pending": "[ ]",
    "cancelled": "[~]",
}


class TodoStore:
    """In-memory session checklist. One instance per CLI/agent session."""

    def __init__(self) -> None:
        self._items: list[dict[str, str]] = []

    def read(self) -> list[dict[str, str]]:
        return [item.copy() for item in self._items]

    def has_items(self) -> bool:
        return bool(self._items)

    def clear(self) -> None:
        self._items.clear()

    def write(
        self,
        todos: list[dict[str, Any]],
        *,
        merge: bool = False,
    ) -> list[dict[str, str]]:
        if not merge:
            self._items = [self._validate(t) for t in self._dedupe_by_id(todos)]
            return self.read()

        existing = {item["id"]: item for item in self._items}
        for raw in self._dedupe_by_id(todos):
            item_id = str(raw.get("id") or "").strip()
            if not item_id:
                continue
            if item_id in existing:
                if "content" in raw and raw["content"]:
                    existing[item_id]["content"] = str(raw["content"]).strip()
                if "status" in raw and raw["status"]:
                    status = str(raw["status"]).strip().lower()
                    if status in VALID_STATUSES:
                        existing[item_id]["status"] = status
            else:
                validated = self._validate(raw)
                existing[validated["id"]] = validated
                self._items.append(validated)

        seen: set[str] = set()
        rebuilt: list[dict[str, str]] = []
        for item in self._items:
            current = existing.get(item["id"], item)
            if current["id"] not in seen:
                rebuilt.append(current)
                seen.add(current["id"])
        self._items = rebuilt
        return self.read()

    def format_display(self) -> str | None:
        if not self._items:
            return None
        lines: list[str] = []
        for item in self._items:
            marker = _STATUS_MARKERS.get(item["status"], "[?]")
            lines.append(f"{marker} {item['id']}: {item['content']}")
        return "\n".join(lines)

    def summary(self) -> dict[str, int]:
        items = self._items
        return {
            "total": len(items),
            "pending": sum(1 for i in items if i["status"] == "pending"),
            "in_progress": sum(1 for i in items if i["status"] == "in_progress"),
            "completed": sum(1 for i in items if i["status"] == "completed"),
            "cancelled": sum(1 for i in items if i["status"] == "cancelled"),
        }

    @staticmethod
    def _validate(item: dict[str, Any]) -> dict[str, str]:
        item_id = str(item.get("id") or "").strip() or "?"
        content = str(item.get("content") or "").strip() or "(no description)"
        status = str(item.get("status") or "pending").strip().lower()
        if status not in VALID_STATUSES:
            status = "pending"
        return {"id": item_id, "content": content, "status": status}

    @staticmethod
    def _dedupe_by_id(todos: list[dict[str, Any]]) -> list[dict[str, Any]]:
        last_index: dict[str, int] = {}
        for i, item in enumerate(todos):
            item_id = str(item.get("id") or "").strip() or "?"
            last_index[item_id] = i
        return [todos[i] for i in sorted(last_index.values())]


class TodoTool(Tool):
    name = "todo"
    description = (
        "Manage your task list for the current session. Use for complex tasks "
        "with 3+ steps or when the user provides multiple tasks "
        "(e.g. research → draft → WhatsApp). "
        "Call with no todos to read the current list.\n\n"
        "Writing:\n"
        "- Provide 'todos' array to create/update items\n"
        "- merge=false (default): replace the entire list with a fresh plan\n"
        "- merge=true: update existing items by id, add any new ones\n\n"
        "Each item: {id, content, status: pending|in_progress|completed|cancelled}\n"
        "List order is priority. Only ONE item in_progress at a time.\n"
        "Mark items completed immediately when done. If something fails, "
        "cancel it and add a revised item.\n\n"
        "Always returns the full current list."
    )
    risk_level = RiskLevel.LOW.value

    def __init__(self, store: TodoStore | None = None) -> None:
        self.store = store or TodoStore()

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "Task items to write. Omit to read current list.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Unique item identifier",
                            },
                            "content": {
                                "type": "string",
                                "description": "Task description",
                            },
                            "status": {
                                "type": "string",
                                "enum": sorted(VALID_STATUSES),
                                "description": "Current status",
                            },
                        },
                        "required": ["id", "content", "status"],
                    },
                },
                "merge": {
                    "type": "boolean",
                    "description": (
                        "true: update existing items by id, add new ones. "
                        "false (default): replace the entire list."
                    ),
                    "default": False,
                },
            },
            "required": [],
        }

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        todos = arguments.get("todos")
        if todos is None:
            return None
        if not isinstance(todos, list):
            return "Error: todos must be an array"
        if len(todos) > 40:
            return "Error: at most 40 todo items"
        for i, item in enumerate(todos):
            if not isinstance(item, dict):
                return f"Error: todos[{i}] must be an object"
        return None

    async def execute(self, arguments: dict[str, Any]) -> str:
        todos = arguments.get("todos")
        merge = bool(arguments.get("merge") or False)

        if todos is not None:
            if not isinstance(todos, list):
                return "Error: todos must be an array"
            items = self.store.write(todos, merge=merge)
        else:
            items = self.store.read()

        in_progress = [i for i in items if i["status"] == "in_progress"]
        warning = None
        if len(in_progress) > 1:
            warning = (
                f"{len(in_progress)} items are in_progress; keep only one active."
            )

        payload: dict[str, Any] = {
            "todos": items,
            "summary": self.store.summary(),
        }
        if warning:
            payload["warning"] = warning
        return json.dumps(payload, ensure_ascii=False, indent=2)
