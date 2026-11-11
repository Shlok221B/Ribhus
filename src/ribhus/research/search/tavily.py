from __future__ import annotations

import httpx

from ribhus.research.canonical import canonicalize_url, lead_priority_score
from ribhus.research.models import SearchLead


class TavilySearchProvider:
    name = "tavily"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key.strip()

    async def search(self, query: str, *, max_results: int = 8) -> list[SearchLead]:
        if not self.api_key:
            return []
        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max(1, min(max_results, 15)),
            "include_answer": False,
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://api.tavily.com/search", json=payload
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError):
            return []
        leads: list[SearchLead] = []
        for item in data.get("results") or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            title = str(item.get("title") or "")
            snippet = str(item.get("content") or item.get("snippet") or "")
            leads.append(
                SearchLead(
                    title=title,
                    url=url,
                    snippet=snippet,
                    provider=self.name,
                    query=query,
                    canonical_url=canonicalize_url(url),
                    score=lead_priority_score(url, title, snippet),
                )
            )
        return leads
