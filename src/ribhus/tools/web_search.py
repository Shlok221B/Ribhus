from __future__ import annotations

from typing import Any

from ddgs import DDGS

from ribhus.tools.base import Tool


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Search the web for current information. "
        "Returns titles, URLs, and short snippets. "
        "For cafes/restaurants near the user, prefer `location` action=nearby "
        "instead — web_search often returns directory sites, not venue names. "
        "If you must search places, query “best cafes in {city area}” (never “near me”) "
        "and web_extract a list to get named shops."
    )
    risk_level = "low"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Number of results (1-10)",
                    "default": 5,
                },
            },
            "required": ["query"],
        }

    async def execute(self, arguments: dict[str, Any]) -> str:
        query = str(arguments.get("query", "")).strip()
        if not query:
            return "Error: query is required"
        max_results = int(arguments.get("max_results") or 5)
        max_results = max(1, min(max_results, 10))

        results = list(DDGS().text(query, max_results=max_results))
        if not results:
            return f"No results found for: {query}"

        lines: list[str] = []
        for i, item in enumerate(results, start=1):
            title = item.get("title") or "(no title)"
            href = item.get("href") or item.get("link") or ""
            body = item.get("body") or item.get("snippet") or ""
            lines.append(f"{i}. {title}\n   URL: {href}\n   {body}")
        return "\n\n".join(lines)
