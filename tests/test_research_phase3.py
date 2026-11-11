import asyncio
from pathlib import Path

import pytest

from ribhus.research.fetch_cache import CachedFetch, FetchCache
from ribhus.research.inspect.http_extract import parse_html
from ribhus.research.models import SearchLead
from ribhus.research.search.registry import multi_search
from ribhus.research.search.select import is_inspect_worthy, select_leads_for_inspect


def test_select_skips_portal_homes_and_help_docs():
    leads = [
        SearchLead(
            title="Jobs",
            url="https://www.linkedin.com/jobs/",
            snippet="Find jobs",
            score=0.4,
            canonical_url="https://linkedin.com/jobs",
        ),
        SearchLead(
            title="Help Center",
            url="https://support.lever.co/hc/en-us",
            snippet="knowledge base",
            score=0.9,
            canonical_url="https://support.lever.co/hc/en-us",
        ),
        SearchLead(
            title="Backend Engineer",
            url="https://boards.greenhouse.io/acme/jobs/123",
            snippet="Apply now",
            score=0.85,
            canonical_url="https://boards.greenhouse.io/acme/jobs/123",
        ),
    ]
    assert not is_inspect_worthy(leads[0])
    assert not is_inspect_worthy(leads[1])
    assert is_inspect_worthy(leads[2])
    chosen = select_leads_for_inspect(leads, max_urls=5)
    assert len(chosen) == 1
    assert "greenhouse" in chosen[0].url


def test_parse_html_extracts_json_ld_and_apply_link():
    html = """
    <html><head><title>Role</title>
    <script type="application/ld+json">
    {"@type":"JobPosting","title":"Backend Eng","hiringOrganization":{"name":"Acme"}}
    </script></head>
    <body><main><a href="/apply">Apply now</a><p>Hello world content for the role.</p></main></body>
    </html>
    """
    snap = parse_html("https://x.test/1", "https://x.test/1", 200, html)
    assert snap.job_postings
    assert any(link.get("kind") == "apply" for link in snap.links)
    assert snap.level == 1


def test_fetch_cache_roundtrip(tmp_path: Path):
    cache = FetchCache(disk_dir=tmp_path, ttl_seconds=60)
    item = CachedFetch(
        url="https://example.com/a",
        final_url="https://example.com/a",
        status_code=200,
        content_type="text/html",
        body="<html><body>hi</body></html>",
        redirect_chain=["https://example.com/a"],
        fetched_at=0,
    )
    # Force fresh timestamp via put after fixing time
    import time

    item.fetched_at = time.time()
    cache.put(item)
    hit = cache.get("https://example.com/a")
    assert hit is not None
    assert "hi" in hit.body


class _FakeProvider:
    name = "fake"

    def __init__(self, leads: list[SearchLead]) -> None:
        self._leads = leads

    async def search(self, query: str, *, max_results: int = 8) -> list[SearchLead]:
        return list(self._leads)


@pytest.mark.asyncio
async def test_multi_search_dedupes_and_boosts_agreement():
    lead_a = SearchLead(
        title="A",
        url="https://boards.greenhouse.io/x/jobs/1",
        snippet="one",
        provider="fake1",
        canonical_url="https://boards.greenhouse.io/x/jobs/1",
        score=0.6,
    )
    lead_b = SearchLead(
        title="A",
        url="https://boards.greenhouse.io/x/jobs/1",
        snippet="longer snippet from second provider about the role",
        provider="fake2",
        canonical_url="https://boards.greenhouse.io/x/jobs/1",
        score=0.55,
    )

    class P1(_FakeProvider):
        name = "p1"

    class P2(_FakeProvider):
        name = "p2"

    results = await multi_search(
        [P1([lead_a]), P2([lead_b])],
        ["python jobs"],
        max_parallel=2,
    )
    assert len(results) == 1
    assert results[0].score > 0.6
    assert "longer snippet" in results[0].snippet
