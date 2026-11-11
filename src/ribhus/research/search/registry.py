from __future__ import annotations

import asyncio
from typing import Any

from ribhus.config import Settings
from ribhus.research.canonical import canonicalize_url
from ribhus.research.models import SearchLead
from ribhus.research.search.brave import BraveSearchProvider
from ribhus.research.search.ddgs_provider import DdgsSearchProvider
from ribhus.research.search.exa import ExaSearchProvider
from ribhus.research.search.tavily import TavilySearchProvider


def build_search_providers(settings: Settings) -> list[Any]:
    providers: list[Any] = [DdgsSearchProvider()]
    if settings.tavily_api_key.strip():
        providers.append(TavilySearchProvider(settings.tavily_api_key))
    if settings.exa_api_key.strip():
        providers.append(ExaSearchProvider(settings.exa_api_key))
    if settings.brave_api_key.strip():
        providers.append(BraveSearchProvider(settings.brave_api_key))
    return providers


async def multi_search(
    providers: list[Any],
    queries: list[str],
    *,
    max_results_per_query: int = 8,
    max_parallel: int = 4,
) -> list[SearchLead]:
    """Run queries across providers; dedupe by canonical URL."""
    sem = asyncio.Semaphore(max(1, max_parallel))
    results: list[SearchLead] = []

    async def _one(provider: Any, query: str) -> list[SearchLead]:
        async with sem:
            try:
                return await provider.search(query, max_results=max_results_per_query)
            except Exception:  # noqa: BLE001
                return []

    tasks = [
        _one(provider, query)
        for query in queries
        for provider in providers
    ]
    batches = await asyncio.gather(*tasks)
    seen: set[str] = set()
    for batch in batches:
        for lead in batch:
            key = lead.canonical_url or canonicalize_url(lead.url)
            if not key or key in seen:
                continue
            seen.add(key)
            lead.canonical_url = key
            results.append(lead)
    results.sort(key=lambda lead: lead.score, reverse=True)
    return results
