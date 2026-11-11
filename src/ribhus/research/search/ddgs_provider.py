from __future__ import annotations

import asyncio

from ddgs import DDGS

from ribhus.research.canonical import canonicalize_url, lead_priority_score
from ribhus.research.models import SearchLead


class DdgsSearchProvider:
    name = "ddgs"

    async def search(self, query: str, *, max_results: int = 8) -> list[SearchLead]:
        def _run() -> list[dict]:
            return list(DDGS().text(query, max_results=max_results))

        raw = await asyncio.to_thread(_run)
        leads: list[SearchLead] = []
        for item in raw:
            url = str(item.get("href") or item.get("link") or "").strip()
            if not url:
                continue
            title = str(item.get("title") or "")
            snippet = str(item.get("body") or item.get("snippet") or "")
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
