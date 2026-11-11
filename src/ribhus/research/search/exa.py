from __future__ import annotations

import httpx

from ribhus.research.canonical import canonicalize_url, lead_priority_score
from ribhus.research.models import SearchLead


class ExaSearchProvider:
    name = "exa"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key.strip()

    async def search(self, query: str, *, max_results: int = 8) -> list[SearchLead]:
        if not self.api_key:
            return []
        payload = {
            "query": query,
            "numResults": max(1, min(max_results, 15)),
            "type": "auto",
            "contents": {"text": {"maxCharacters": 400}},
        }
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://api.exa.ai/search", json=payload, headers=headers
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
            text = item.get("text") or item.get("snippet") or ""
            snippet = str(text)[:500]
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
