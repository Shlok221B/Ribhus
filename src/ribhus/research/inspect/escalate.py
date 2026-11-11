"""Decide when to escalate page inspection L1 → L2 → L3."""

from __future__ import annotations

import asyncio
import logging

from ribhus.research.inspect.browser_inspect import browser_interact_apply, browser_render
from ribhus.research.inspect.http_extract import PageSnapshot, fetch_page
from ribhus.research.models import SearchLead
from ribhus.research.search.select import select_leads_for_inspect
from ribhus.tools.browser import BrowserSession

logger = logging.getLogger(__name__)


def _needs_browser(snap: PageSnapshot, lead: SearchLead | None = None) -> bool:
    if snap.robots_allowed is False:
        return False
    if snap.thin or snap.error or snap.status_code == 0:
        return True
    if snap.status_code == 200 and not snap.job_postings:
        has_apply = any(link.get("kind") == "apply" for link in snap.links)
        if not has_apply and len(snap.text) < 800:
            return True
        if lead is not None and lead.score >= 0.7 and not has_apply and not snap.job_postings:
            return True
    return False


async def investigate_url(
    url: str,
    *,
    browser: BrowserSession | None = None,
    allow_browser: bool = True,
    allow_interact: bool = True,
    max_chars: int = 16_000,
    respect_robots: bool = True,
    retries: int = 2,
) -> PageSnapshot:
    snap = await fetch_page(
        url,
        max_chars=max_chars,
        respect_robots=respect_robots,
        retries=retries,
    )
    if snap.robots_allowed is False:
        return snap

    needs_browser = allow_browser and browser is not None and _needs_browser(snap)
    if not needs_browser:
        return snap

    rendered = await browser_render(browser, url, max_chars=max_chars)
    if rendered.error and not rendered.text:
        # Keep L1 evidence if browser failed
        if snap.text:
            snap.error = f"{snap.error or ''}; browser: {rendered.error}".strip("; ")
            return snap
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
    max_browser_pages: int = 6,
    respect_robots: bool = True,
    retries: int = 2,
) -> list[PageSnapshot]:
    """Investigate top leads: parallel L1, then sequential browser for thin pages."""
    chosen = select_leads_for_inspect(leads, max_urls=max(0, max_urls))
    if not chosen:
        # Fall back to top-N raw leads if filters removed everything
        chosen = leads[: max(0, max_urls)]
    if not chosen:
        return []

    sem = asyncio.Semaphore(max(1, max_parallel_http))

    async def _http(lead: SearchLead) -> PageSnapshot:
        async with sem:
            return await fetch_page(
                lead.url, respect_robots=respect_robots, retries=retries
            )

    http_snaps = await asyncio.gather(*[_http(lead) for lead in chosen])
    results: list[PageSnapshot] = []
    browser_budget = max(0, max_browser_pages)

    for lead, snap in zip(chosen, http_snaps, strict=True):
        escalate = (
            allow_browser
            and browser is not None
            and browser_budget > 0
            and _needs_browser(snap, lead)
        )
        if escalate:
            browser_budget -= 1
            logger.debug("Escalating %s to browser (L2/L3)", lead.url)
            rendered = await investigate_url(
                lead.url,
                browser=browser,
                allow_browser=True,
                allow_interact=True,
                respect_robots=respect_robots,
                retries=retries,
            )
            results.append(rendered)
        else:
            results.append(snap)
    return results
