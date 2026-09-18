from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ribhus.policy.levels import RiskLevel
from ribhus.tools.base import Tool
from ribhus.tools.process_registry import ProcessRegistry
from ribhus.tools.terminal import _BLOCKED_PATTERNS


def _fmt(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


class ProcessTool(Tool):
    name = "process"
    description = (
        "Manage background shell processes in the workspace. "
        "Actions: start (launch command, returns session_id), list, "
        "poll (status + new output), log (full/paginated output), "
        "wait (block until done or timeout), kill, write (stdin), "
        "submit (stdin + newline). Use for long installs, servers, watches, "
        "or any command that would exceed the one-shot terminal timeout. "
        "Prefer terminal for short commands."
    )
    risk_level = RiskLevel.HIGH.value

    def __init__(self, registry: ProcessRegistry) -> None:
        self.registry = registry

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "start",
                        "list",
                        "poll",
                        "log",
                        "wait",
                        "kill",
                        "write",
                        "submit",
                    ],
                    "description": "Process action to perform",
                },
                "command": {
                    "type": "string",
                    "description": "Shell command (required for start)",
                },
                "session_id": {
                    "type": "string",
                    "description": "Process id from start (required except start/list)",
                },
                "data": {
                    "type": "string",
                    "description": "Stdin data for write/submit",
                },
                "timeout": {
                    "type": "number",
                    "description": "Seconds to wait (wait action only; default 120, max 600)",
                },
                "offset": {
                    "type": "integer",
                    "description": "Character offset for log pagination",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max characters to return from log",
                },
            },
            "required": ["action"],
        }

    def risk_for_arguments(self, arguments: dict[str, Any]) -> RiskLevel:
        action = str(arguments.get("action") or "").lower()
        if action in {"list", "poll", "log"}:
            return RiskLevel.LOW
        if action == "wait":
            return RiskLevel.MEDIUM
        return RiskLevel.HIGH

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        action = str(arguments.get("action") or "").strip().lower()
        if not action:
            return "Error: action is required"
        if action == "start":
            command = str(arguments.get("command") or "").strip()
            if not command:
                return "Error: command is required for start"
            lowered = command.lower()
            for pattern in _BLOCKED_PATTERNS:
                if pattern in lowered:
                    return (
                        f"Error: command blocked for safety "
                        f"(matched '{pattern}')"
                    )
        elif action in {"poll", "log", "wait", "kill", "write", "submit"}:
            if not str(arguments.get("session_id") or "").strip():
                return f"Error: session_id is required for {action}"
        elif action == "list":
            return None
        else:
            return (
                "Error: unknown action. Use start, list, poll, log, "
                "wait, kill, write, or submit."
            )
        return None

    async def execute(self, arguments: dict[str, Any]) -> str:
        action = str(arguments.get("action") or "").strip().lower()
        try:
            if action == "start":
                return await self._start(arguments)
            if action == "list":
                return _fmt({"processes": self.registry.list_sessions()})
            if action == "poll":
                return _fmt(self.registry.poll(str(arguments["session_id"]).strip()))
            if action == "log":
                offset = int(arguments.get("offset") or 0)
                limit = int(arguments.get("limit") or 8_000)
                return _fmt(
                    self.registry.log(
                        str(arguments["session_id"]).strip(),
                        offset=offset,
                        limit=limit,
                    )
                )
            if action == "wait":
                timeout = arguments.get("timeout")
                return _fmt(
                    await self.registry.wait(
                        str(arguments["session_id"]).strip(),
                        timeout=float(timeout) if timeout is not None else None,
                    )
                )
            if action == "kill":
                return _fmt(
                    await self.registry.kill(str(arguments["session_id"]).strip())
                )
            if action in {"write", "submit"}:
                data = arguments.get("data")
                if data is None:
                    data = ""
                return _fmt(
                    await self.registry.write(
                        str(arguments["session_id"]).strip(),
                        str(data),
                        submit=action == "submit",
                    )
                )
            return "Error: unknown action"
        except (ValueError, RuntimeError) as exc:
            return f"Error: {exc}"

    async def _start(self, arguments: dict[str, Any]) -> str:
        command = str(arguments.get("command") or "").strip()
        session = await self.registry.start(command, cwd=self.registry.workspace)
        payload = session.summary()
        payload["hint"] = (
            "Process started in background. Use process action=poll/log/wait "
            "with this session_id; kill when finished watching."
        )
        return _fmt(payload)


def make_process_tool(workspace: Path) -> ProcessTool:
    return ProcessTool(ProcessRegistry(workspace))
