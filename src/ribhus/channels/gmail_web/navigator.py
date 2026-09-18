"""Navigate Gmail inbox: list rows, search, open threads."""

from __future__ import annotations

import asyncio
import re

from ribhus.channels.gmail_web.selectors import (
    GMAIL_URL,
    INBOX_ROWS,
    SEARCH_BOX,
    THREAD_SUBJECT,
    any_visible,
    first_visible,
)
from ribhus.channels.gmail_web.session import GmailSession

_LIST_ROWS = """
() => {
  const rows = [];
  const seen = new Set();
  const candidates = document.querySelectorAll(
    "div[role='main'] tr.zA, div[role='main'] tr[role='row']"
  );
  for (const tr of candidates) {
    const subjectEl =
      tr.querySelector("span.bog") ||
      tr.querySelector("[data-thread-id] span") ||
      tr.querySelector("span[class*='bog']") ||
      tr.querySelector("td span");
    const fromEl =
      tr.querySelector("span.zF") ||
      tr.querySelector("span.yP") ||
      tr.querySelector("[email]") ||
      tr.querySelector("span[name]");
    const subject = (subjectEl && (subjectEl.getAttribute('data-thread-id')
      ? subjectEl.textContent : subjectEl.textContent) || '').trim();
    let from = '';
    if (fromEl) {
      from = (fromEl.getAttribute('email') || fromEl.getAttribute('name')
        || fromEl.textContent || '').trim();
    }
    const snippetEl = tr.querySelector("span.y2");
    const snippet = (snippetEl && snippetEl.textContent || '').trim();
    if (!subject && !from) continue;
    const key = (from + '|' + subject).toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    rows.push({ from, subject: subject || '(no subject)', snippet });
    if (rows.length >= 25) break;
  }
  return rows;
}
"""


class ThreadNotFound(Exception):
    pass


class GmailNavigator:
    def __init__(self, session: GmailSession) -> None:
        self.session = session

    async def go_inbox(self) -> None:
        page = await self.session.ensure_logged_in()
        if "#inbox" not in (page.url or "") and "mail.google.com" in (page.url or ""):
            await page.goto(GMAIL_URL, wait_until="domcontentloaded", timeout=45_000)
            await asyncio.sleep(0.8)
        await any_visible(page, INBOX_ROWS, timeout_ms=12_000)

    async def list_inbox(self, *, limit: int = 10) -> list[dict[str, str]]:
        page = await self.session.ensure_logged_in()
        await self.go_inbox()
        await asyncio.sleep(0.5)
        try:
            rows = await page.evaluate(_LIST_ROWS)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Could not list Gmail inbox: {exc}") from exc
        if not isinstance(rows, list):
            return []
        out = []
        for row in rows[: max(1, min(limit, 25))]:
            if isinstance(row, dict):
                out.append(
                    {
                        "from": str(row.get("from") or ""),
                        "subject": str(row.get("subject") or "(no subject)"),
                        "snippet": str(row.get("snippet") or ""),
                    }
                )
        return out

    async def open_thread(self, query: str) -> str:
        """Open a thread by subject/search query. Returns opened subject if found."""
        q = (query or "").strip()
        if not q:
            raise ThreadNotFound("query/subject is required")

        page = await self.session.ensure_logged_in()
        await self.go_inbox()

        # Try visible row click first
        clicked = await page.evaluate(
            """(q) => {
              const needle = (q || '').toLowerCase();
              const rows = document.querySelectorAll(
                "div[role='main'] tr.zA, div[role='main'] tr[role='row']"
              );
              for (const tr of rows) {
                const text = (tr.innerText || '').toLowerCase();
                if (text.includes(needle)) {
                  tr.click();
                  return true;
                }
              }
              return false;
            }""",
            q,
        )
        if not clicked:
            box = await first_visible(page, SEARCH_BOX, timeout_ms=5_000)
            if box is None:
                raise ThreadNotFound(
                    f"Could not find inbox row or search box for {q!r}"
                )
            await box.click()
            await page.keyboard.press("Meta+A")
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
            await page.keyboard.insert_text(q)
            await page.keyboard.press("Enter")
            await asyncio.sleep(1.2)
            clicked = await page.evaluate(
                """(q) => {
                  const needle = (q || '').toLowerCase();
                  const rows = document.querySelectorAll(
                    "div[role='main'] tr.zA, div[role='main'] tr[role='row']"
                  );
                  for (const tr of rows) {
                    const text = (tr.innerText || '').toLowerCase();
                    if (!needle || text.includes(needle)) {
                      tr.click();
                      return true;
                    }
                  }
                  return false;
                }""",
                q,
            )
            if not clicked:
                raise ThreadNotFound(f"No Gmail thread matched {q!r}")

        await asyncio.sleep(0.8)
        subject = await self._open_subject()
        return subject or q

    async def _open_subject(self) -> str:
        page = self.session.page
        if page is None:
            return ""
        for selector in THREAD_SUBJECT:
            try:
                loc = page.locator(selector).first
                await loc.wait_for(state="visible", timeout=2_500)
                text = (await loc.inner_text()).strip()
                if text:
                    return text
            except Exception:  # noqa: BLE001
                continue
        # fallback: page title
        try:
            title = await page.title()
            title = re.sub(r"\s*-?\s*Gmail.*$", "", title).strip()
            return title
        except Exception:  # noqa: BLE001
            return ""
