from __future__ import annotations

import json
from typing import Any

from ribhus.policy.levels import RiskLevel
from ribhus.tools.base import Tool


def _format_mcp_result(result: Any) -> str:
    """Turn an MCP CallToolResult into a string for the model."""
    is_error = bool(getattr(result, "is_error", False) or getattr(result, "isError", False))
    parts: list[str] = []

    structured = getattr(result, "structured_content", None) or getattr(
        result, "structuredContent", None
    )
    if structured is not None:
        try:
            parts.append(json.dumps(structured, ensure_ascii=False, indent=2))
        except TypeError:
            parts.append(str(structured))

    content = getattr(result, "content", None) or []
    for block in content:
        text = getattr(block, "text", None)
        if text is not None:
            if not parts or text not in parts[0]:
                parts.append(str(text))
            continue
        # Fallback for non-text blocks
        try:
            parts.append(json.dumps(block.model_dump(), ensure_ascii=False))
        except Exception:  # noqa: BLE001
            parts.append(str(block))

    body = "\n".join(p for p in parts if p).strip() or "(empty MCP result)"
    if is_error:
        return f"Error from MCP tool: {body}"
    return body


class McpProxyTool(Tool):
    """Ribhus Tool that forwards to one tool on an MCP server."""

    def __init__(
        self,
        *,
        server_name: str,
        remote_name: str,
        description: str,
        input_schema: dict[str, Any],
        risk: str,
        caller,
    ) -> None:
        self.server_name = server_name
        self.remote_name = remote_name
        self.name = f"{server_name}__{remote_name}"
        self.description = (
            f"[MCP:{server_name}] {description or remote_name}"
        ).strip()
        self.risk_level = RiskLevel.parse(risk).value
        self._input_schema = input_schema or {
            "type": "object",
            "properties": {},
        }
        self._caller = caller

    def input_schema(self) -> dict[str, Any]:
        schema = dict(self._input_schema)
        # Models expect JSON Schema objects; strip non-schema noise if present.
        schema.setdefault("type", "object")
        return schema

    async def execute(self, arguments: dict[str, Any]) -> str:
        try:
            result = await self._caller(self.remote_name, arguments or {})
        except Exception as exc:  # noqa: BLE001
            return f"Error calling MCP {self.name}: {exc}"
        return _format_mcp_result(result)
