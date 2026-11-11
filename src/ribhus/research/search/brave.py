from __future__ import annotations

import httpx

from ribhus.research.canonical import canonicalize_url, lead_priority_score
from ribhus.research.models import SearchLead


class BraveSearchProvider:
    name = "brave"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key.strip()

    async def search(self, query: str, *, max_results: int = 8) -> list[SearchLead]:
        if not self.api_key:
            return []
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self.api_key,
        }
        params = {"q": query, "count": max(1, min(max_results, 15))}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers=headers,
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError):
            return []
        web = data.get("web") if isinstance(data, dict) else None
        results = (web or {}).get("results") if isinstance(web, dict) else []
        leads: list[SearchLead] = []
        for item in results or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            title = str(item.get("title") or "")
            snippet = str(item.get("description") or "")
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
