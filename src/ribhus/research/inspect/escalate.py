"""Decide when to escalate page inspection L1 → L2 → L3."""

from __future__ import annotations

import asyncio
from ribhus.research.inspect.browser_inspect import browser_interact_apply, browser_render
from ribhus.research.inspect.http_extract import PageSnapshot, fetch_page
from ribhus.research.models import SearchLead
from ribhus.tools.browser import BrowserSession


async def investigate_url(
    url: str,
    *,
    browser: BrowserSession | None = None,
    allow_browser: bool = True,
    allow_interact: bool = True,
    max_chars: int = 16_000,
) -> PageSnapshot:
    snap = await fetch_page(url, max_chars=max_chars)
    needs_browser = (
        allow_browser
        and browser is not None
        and (snap.thin or snap.error or (snap.status_code == 0))
    )
    # Also escalate when we have HTML but no job signals and look JS-heavy
    if (
        allow_browser
        and browser is not None
        and not needs_browser
        and snap.status_code == 200
        and not snap.job_postings
        and not any(link.get("kind") == "apply" for link in snap.links)
        and len(snap.text) < 800
    ):
        needs_browser = True

    if not needs_browser:
        return snap

    rendered = await browser_render(browser, url, max_chars=max_chars)
    if rendered.error and not rendered.text:
        return rendered

    need_interact = (
        allow_interact
        and not any(link.get("kind") == "apply" for link in rendered.links)
        and not rendered.job_postings
        and "apply" in rendered.text.lower()
    )
    if need_interact:
        interacted = await browser_interact_apply(browser, max_chars=max_chars)
        if interacted.text or not interacted.error:
            return interacted
    return rendered


async def investigate_leads(
    leads: list[SearchLead],
    *,
    browser: BrowserSession | None = None,
    max_urls: int = 12,
    max_parallel_http: int = 4,
    allow_browser: bool = True,
) -> list[PageSnapshot]:
    """Investigate top leads: parallel L1, then sequential browser for thin pages."""
    chosen = leads[: max(0, max_urls)]
    if not chosen:
        return []

    sem = asyncio.Semaphore(max(1, max_parallel_http))

    async def _http(lead: SearchLead) -> PageSnapshot:
        async with sem:
            return await fetch_page(lead.url)

    http_snaps = await asyncio.gather(*[_http(lead) for lead in chosen])
    results: list[PageSnapshot] = []
    browser_budget = 6

    for lead, snap in zip(chosen, http_snaps, strict=True):
        escalate = (
            allow_browser
            and browser is not None
            and browser_budget > 0
            and (
                snap.thin
                or snap.error
                or (
                    not snap.job_postings
                    and not any(link.get("kind") == "apply" for link in snap.links)
                    and lead.score >= 0.55
                )
            )
        )
        if escalate:
            browser_budget -= 1
            rendered = await investigate_url(
                lead.url,
                browser=browser,
                allow_browser=True,
                allow_interact=True,
            )
            results.append(rendered)
        else:
            results.append(snap)
    return results
