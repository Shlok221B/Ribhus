from __future__ import annotations

import asyncio
import logging
from typing import Any

from ribhus.config import Settings
from ribhus.research.canonical import canonicalize_url
from ribhus.research.models import SearchLead
from ribhus.research.search.brave import BraveSearchProvider
from ribhus.research.search.ddgs_provider import DdgsSearchProvider
from ribhus.research.search.exa import ExaSearchProvider
from ribhus.research.search.tavily import TavilySearchProvider

logger = logging.getLogger(__name__)


def build_search_providers(settings: Settings) -> list[Any]:
    providers: list[Any] = [DdgsSearchProvider()]
    if settings.tavily_api_key.strip():
        providers.append(TavilySearchProvider(settings.tavily_api_key))
    if settings.exa_api_key.strip():
        providers.append(ExaSearchProvider(settings.exa_api_key))
    if settings.brave_api_key.strip():
        providers.append(BraveSearchProvider(settings.brave_api_key))
    return providers


def provider_names(providers: list[Any]) -> list[str]:
    return [getattr(p, "name", type(p).__name__) for p in providers]


async def multi_search(
    providers: list[Any],
    queries: list[str],
    *,
    max_results_per_query: int = 8,
    max_parallel: int = 4,
) -> list[SearchLead]:
    """Run queries across providers; dedupe by canonical URL; boost multi-provider hits."""
    if not providers or not queries:
        return []

    sem = asyncio.Semaphore(max(1, max_parallel))
    provider_hits: dict[str, int] = {provider_names([p])[0]: 0 for p in providers}

    async def _one(provider: Any, query: str) -> tuple[str, list[SearchLead]]:
        name = getattr(provider, "name", type(provider).__name__)
        async with sem:
            try:
                leads = await provider.search(query, max_results=max_results_per_query)
                return name, leads
            except Exception as exc:  # noqa: BLE001
                logger.warning("Search provider %s failed for %r: %s", name, query, exc)
                return name, []

    tasks = [
        _one(provider, query) for query in queries for provider in providers
    ]
    batches = await asyncio.gather(*tasks)

    by_url: dict[str, SearchLead] = {}
    providers_for_url: dict[str, set[str]] = {}

    for name, batch in batches:
        provider_hits[name] = provider_hits.get(name, 0) + len(batch)
        for lead in batch:
            key = lead.canonical_url or canonicalize_url(lead.url)
            if not key:
                continue
            lead.canonical_url = key
            providers_for_url.setdefault(key, set()).add(name)
            existing = by_url.get(key)
            if existing is None:
                by_url[key] = lead
                continue
            # Keep richer snippet / higher score; note multi-provider agreement
            if lead.score > existing.score:
                merged = lead.model_copy()
            else:
                merged = existing.model_copy()
            if len(lead.snippet or "") > len(merged.snippet or ""):
                merged.snippet = lead.snippet
            if not merged.title and lead.title:
                merged.title = lead.title
            by_url[key] = merged

    results: list[SearchLead] = []
    for key, lead in by_url.items():
        agreement = len(providers_for_url.get(key, ()))
        if agreement > 1:
            lead.score = min(1.0, lead.score + 0.08 * (agreement - 1))
            # Encode provider diversity lightly in snippet metadata if empty provider
            if lead.provider and agreement > 1:
                lead.provider = f"{lead.provider}+{agreement - 1}"
        results.append(lead)

    results.sort(key=lambda item: item.score, reverse=True)
    logger.info(
        "multi_search: %s queries × %s providers → %s unique leads (%s)",
        len(queries),
        len(providers),
        len(results),
        provider_hits,
    )
    return results
