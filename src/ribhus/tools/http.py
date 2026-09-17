from __future__ import annotations

from typing import Any

import httpx

from ribhus.tools.base import Tool


class HttpRequestTool(Tool):
    name = "http_request"
    description = (
        "Make an HTTP request to a URL. Useful for fetching APIs or public pages. "
        "Response body is truncated to 50KB."
    )
    risk_level = "medium"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full URL"},
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"],
                    "default": "GET",
                },
                "headers": {
                    "type": "object",
                    "description": "Optional HTTP headers",
                    "additionalProperties": {"type": "string"},
                },
                "body": {
                    "type": "string",
                    "description": "Optional request body (for POST/PUT/PATCH)",
                },
            },
            "required": ["url"],
        }

    async def execute(self, arguments: dict[str, Any]) -> str:
        url = str(arguments.get("url", "")).strip()
        if not url:
            return "Error: url is required"
        method = str(arguments.get("method") or "GET").upper()
        headers = arguments.get("headers") or {}
        body = arguments.get("body")

        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            response = await client.request(
                method,
                url,
                headers=headers if isinstance(headers, dict) else None,
                content=body.encode("utf-8") if isinstance(body, str) else body,
            )

        text = response.text
        if len(text) > 50_000:
            text = text[:50_000] + "\n...[truncated]"

        return (
            f"Status: {response.status_code}\n"
            f"Content-Type: {response.headers.get('content-type', '')}\n\n"
            f"{text}"
        )
