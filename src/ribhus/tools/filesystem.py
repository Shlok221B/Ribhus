from __future__ import annotations

from pathlib import Path
from typing import Any

from ribhus.tools.base import Tool


def _resolve_path(workspace: Path, path_str: str) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = workspace / path
    resolved = path.resolve()
    workspace_resolved = workspace.resolve()
    if not str(resolved).startswith(str(workspace_resolved)):
        raise PermissionError(
            f"Path '{path_str}' is outside the workspace ({workspace_resolved})"
        )
    return resolved


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read a text file relative to the workspace. Truncated at 100KB."
    risk_level = "low"

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to workspace (or absolute within workspace)",
                },
            },
            "required": ["path"],
        }

    async def execute(self, arguments: dict[str, Any]) -> str:
        path_str = str(arguments.get("path", "")).strip()
        if not path_str:
            return "Error: path is required"
        try:
            path = _resolve_path(self.workspace, path_str)
        except PermissionError as exc:
            return f"Error: {exc}"
        if not path.exists():
            return f"Error: file not found: {path_str}"
        if not path.is_file():
            return f"Error: not a file: {path_str}"
        data = path.read_bytes()
        if len(data) > 100_000:
            data = data[:100_000]
            truncated = True
        else:
            truncated = False
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return f"Error: file is not valid UTF-8 text ({path_str})"
        if truncated:
            text += "\n...[truncated]"
        return text


class WriteFileTool(Tool):
    name = "write_file"
    description = "Write text content to a file inside the workspace. Creates parent dirs."
    risk_level = "high"

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to workspace",
                },
                "content": {
                    "type": "string",
                    "description": "Full file contents to write",
                },
            },
            "required": ["path", "content"],
        }

    async def execute(self, arguments: dict[str, Any]) -> str:
        path_str = str(arguments.get("path", "")).strip()
        content = arguments.get("content")
        if not path_str:
            return "Error: path is required"
        if content is None:
            return "Error: content is required"
        try:
            path = _resolve_path(self.workspace, path_str)
        except PermissionError as exc:
            return f"Error: {exc}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content), encoding="utf-8")
        return f"Wrote {len(str(content))} characters to {path_str}"
