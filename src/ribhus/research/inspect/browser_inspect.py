"""Level 2–3: Playwright page investigation via BrowserSession."""

from __future__ import annotations

import logging

from ribhus.research.inspect.http_extract import PageSnapshot, parse_html
from ribhus.tools.browser import BrowserSession
from ribhus.tools.browser_snapshot import format_snapshot, stamp_interactive

logger = logging.getLogger(__name__)


async def browser_render(
    session: BrowserSession,
    url: str,
    *,
    max_chars: int = 16_000,
) -> PageSnapshot:
    """L2: open URL and capture rendered HTML / accessibility snapshot."""
    try:
        session.check_url(url)
        page = await session.ensure()
        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        try:
            await page.wait_for_load_state("networkidle", timeout=8_000)
        except Exception:  # noqa: BLE001
            pass
        final = page.url
        html = await page.content()
        snap = parse_html(url, final, 200, html, max_chars=max_chars)
        snap.level = 2
        try:
            stamped = await stamp_interactive(page)
            a11y = format_snapshot(stamped, full=False)
            if a11y and len(a11y) > 80:
                snap.text = (snap.text + "\n\n--- a11y snapshot ---\n" + a11y)[
                    : max_chars + 2000
                ]
                snap.thin = len(snap.text.strip()) < 280 and not snap.job_postings
        except Exception as exc:  # noqa: BLE001
            logger.debug("a11y snapshot skipped: %s", exc)
        return snap
    except Exception as exc:  # noqa: BLE001
        return PageSnapshot(
            url=url,
            final_url=url,
            status_code=0,
            error=str(exc),
            thin=True,
            level=2,
        )


async def browser_interact_apply(
    session: BrowserSession,
    *,
    max_chars: int = 16_000,
) -> PageSnapshot:
    """L3: try clicking an Apply-like control; never submit forms."""
    try:
        page = await session.ensure()
        candidates = [
            page.get_by_role("link", name="Apply"),
            page.get_by_role("button", name="Apply"),
            page.get_by_role("link", name="Apply for this job"),
            page.get_by_text("Apply now", exact=False),
        ]
        clicked = False
        for locator in candidates:
            try:
                target = locator.first
                if await target.count() == 0:
                    continue
                await target.click(timeout=5_000)
                clicked = True
                break
            except Exception:  # noqa: BLE001
                continue
        if clicked:
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10_000)
            except Exception:  # noqa: BLE001
                pass
        html = await page.content()
        snap = parse_html(page.url, page.url, 200, html, max_chars=max_chars)
        snap.level = 3
        return snap
    except Exception as exc:  # noqa: BLE001
        return PageSnapshot(
            url="",
            final_url="",
            status_code=0,
            error=str(exc),
            thin=True,
            level=3,
        )
