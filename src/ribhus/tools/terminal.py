from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ribhus.tools.base import Tool

# Block destructive / long-hanging setup commands (not a full sandbox).
_BLOCKED_PATTERNS = (
    "rm -rf /",
    "mkfs",
    ":(){",
    "dd if=",
    "shutdown",
    "reboot",
    "playwright install",
    "npx playwright install",
    "uv run playwright install",
)


class TerminalTool(Tool):
    name = "terminal"
    description = (
        "Run a shell command in the workspace directory. "
        "Prefer non-interactive commands. Timeout: 60s."
    )
    risk_level = "high"

    def __init__(self, workspace: Path, timeout: float = 60.0) -> None:
        self.workspace = workspace
        self.timeout = timeout

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to run",
                },
            },
            "required": ["command"],
        }

    async def execute(self, arguments: dict[str, Any]) -> str:
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            return "Error: command is required"

        lowered = command.lower()
        for pattern in _BLOCKED_PATTERNS:
            if pattern in lowered:
                return f"Error: command blocked for safety (matched '{pattern}')"

        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(self.workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.timeout,
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return f"Error: command timed out after {self.timeout}s"

        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        if len(out) > 50_000:
            out = out[:50_000] + "\n...[truncated]"
        if len(err) > 20_000:
            err = err[:20_000] + "\n...[truncated]"

        parts = [f"exit_code={proc.returncode}", f"command: {command}"]
        if out:
            parts.append(f"stdout:\n{out}")
        if err:
            parts.append(f"stderr:\n{err}")
        return "\n".join(parts)
