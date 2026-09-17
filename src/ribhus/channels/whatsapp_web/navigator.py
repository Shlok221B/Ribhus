"""Find and open a WhatsApp chat by contact / group name.

Looks at the already-visible chat list first (the common case: the chat is
right there in the sidebar). Search is only a fallback.
"""

from __future__ import annotations

import asyncio
import re

from ribhus.channels.whatsapp_web.selectors import (
    CHAT_HEADER_TITLE,
    CHAT_LIST,
    CHAT_ROWS,
    MAIN_PANEL,
    SEARCH_BOX,
    SEARCH_ICON,
    any_visible,
    first_visible,
)
from ribhus.channels.whatsapp_web.session import WhatsAppSession

_LIST_CHAT_NAMES = """
() => {
  const pane =
    document.querySelector('#pane-side, [aria-label="Chat list"], [data-testid="chat-list"], #side')
    || document.body;
  const names = [];
  const seen = new Set();
  const add = (raw) => {
    const name = (raw || '').trim();
    if (!name || name.length > 80) return;
    if (/^\\d{1,2}:\\d{2}/.test(name)) return;
    if (/^(today|yesterday|today,|yesterday,)$/i.test(name)) return;
    const key = name.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    names.push(name);
  };
  for (const el of pane.querySelectorAll('[title]')) {
    add(el.getAttribute('title'));
  }
  for (const el of pane.querySelectorAll('[role="listitem"], [role="row"]')) {
    const label = el.getAttribute('aria-label') || '';
    add(label.split(/[:\\n]/)[0]);
    const span = el.querySelector('span[dir="auto"], span[title]');
    if (span) add(span.getAttribute('title') || span.textContent);
  }
  return names;
}
"""

_HEADER_CANDIDATES = """
() => {
  const chrome = /^(profile details|contact info|contact information|group info|chat info|search|menu|video call|voice call|more options|unmute|mute)$/i;
  const main = document.querySelector('#main');
  if (!main) return [];
  const header = main.querySelector('header');
  if (!header) return [];
  const out = [];
  const seen = new Set();
  const add = (raw) => {
    const t = (raw || '').trim();
    if (!t || t.length > 80 || chrome.test(t)) return;
    const k = t.toLowerCase();
    if (seen.has(k)) return;
    seen.add(k);
    out.push(t);
  };
  for (const el of header.querySelectorAll('[title]')) add(el.getAttribute('title'));
  for (const el of header.querySelectorAll('span[dir="auto"], h2, [role="button"]')) {
    add(el.textContent);
  }
  for (const el of header.querySelectorAll('[aria-label]')) {
    const a = el.getAttribute('aria-label') || '';
    for (const part of a.split(/[.\\n]/)) add(part);
  }
  return out;
}
"""

_CHROME_LABELS = {
    "profile details",
    "contact info",
    "contact information",
    "group info",
    "chat info",
    "search",
    "menu",
    "video call",
    "voice call",
    "more options",
    "unmute",
    "mute",
}


class ChatNotFound(Exception):
    pass


def is_chrome_label(title: str | None) -> bool:
    if not title:
        return False
    return title.strip().casefold() in _CHROME_LABELS


def names_match(title: str | None, query: str) -> bool:
    """Loose match: case, emoji, and 'Gupta ji' vs 'Guptaji'."""
    if not title or not query:
        return False
    t = _normalize(title)
    q = _normalize(query)
    if not t or not q:
        return False
    if t == q or q in t or t in q:
        return True
    tc, qc = _compact(title), _compact(query)
    return bool(tc and qc) and (tc == qc or qc in tc or tc in qc)


def pick_matching_name(names: list[str], query: str) -> str | None:
    """Prefer exact/compact-equal names over substring matches."""
    exact: list[str] = []
    partial: list[str] = []
    qn, qc = _normalize(query), _compact(query)
    for name in names:
        if not names_match(name, query):
            continue
        nn, nc = _normalize(name), _compact(name)
        if nn == qn or nc == qc:
            exact.append(name)
        else:
            partial.append(name)
    if exact:
        return exact[0]
    if partial:
        return partial[0]
    return None


def _normalize(value: str) -> str:
    value = value.casefold().strip()
    value = re.sub(r"[^\w\s]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def _compact(value: str) -> str:
    return _normalize(value).replace(" ", "")


class WhatsAppNavigator:
    def __init__(self, session: WhatsAppSession) -> None:
        self.session = session

    async def current_title(self) -> str | None:
        page = self.session.page
        if page is None:
            return None
        candidates = await self.header_candidates()
        for name in candidates:
            if not is_chrome_label(name):
                return name
        loc = await first_visible(page, CHAT_HEADER_TITLE, timeout_ms=1_200)
        if loc is not None:
            title = (await loc.inner_text()).strip()
            if title and not is_chrome_label(title):
                return title
        return None

    async def header_candidates(self) -> list[str]:
        page = self.session.page
        if page is None:
            return []
        try:
            raw = await page.evaluate(_HEADER_CANDIDATES)
        except Exception:  # noqa: BLE001
            return []
        return [str(n).strip() for n in (raw or []) if str(n).strip()]

    async def main_open(self) -> bool:
        page = self.session.page
        if page is None:
            return False
        return await any_visible(page, MAIN_PANEL, timeout_ms=1_500)

    async def list_chat_names(self) -> list[str]:
        page = self.session.page
        if page is None:
            return []
        try:
            names = await page.evaluate(_LIST_CHAT_NAMES)
        except Exception:  # noqa: BLE001
            return []
        return [
            str(n)
            for n in (names or [])
            if str(n).strip() and not is_chrome_label(str(n))
        ]

    async def open_chat(self, name: str) -> str:
        query = name.strip()
        if not query:
            raise ChatNotFound("Contact name is empty.")

        page = await self.session.ensure_logged_in()
        await self._wait_for_chats(page)
        await self._dismiss_overlays(page)

        current = await self.current_title()
        if names_match(current, query):
            return current or query
        matched_header = pick_matching_name(await self.header_candidates(), query)
        if matched_header:
            return matched_header

        if await self._click_listed_chat(page, query):
            return await self._confirm_open(page, query, clicked=True)

        if await self._search_and_open(page, query):
            return await self._confirm_open(page, query, clicked=True)

        visible = await self.list_chat_names()
        hint = (
            f" Visible chats: {', '.join(visible[:12])}."
            if visible
            else " No chat names were readable in the sidebar."
        )
        raise ChatNotFound(
            f"No chat matching '{query}'.{hint} "
            "If the conversation is on screen, the WhatsApp Web layout may have changed."
        )

    async def _wait_for_chats(self, page) -> None:
        await any_visible(page, CHAT_ROWS + CHAT_LIST, timeout_ms=20_000)
        await asyncio.sleep(0.4)

    async def _dismiss_overlays(self, page) -> None:
        """Close the contact-info drawer only. Escape on a chat can close it."""
        try:
            overlay = page.get_by_text("Profile details", exact=True)
            if await overlay.count() == 0:
                return
            loc = overlay.first
            if not await loc.is_visible():
                return
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.25)
        except Exception:  # noqa: BLE001
            return

    async def _confirm_open(self, page, query: str, *, clicked: bool = False) -> str:
        await asyncio.sleep(0.4)
        await self._dismiss_overlays(page)
        title = await self.current_title()
        if names_match(title, query):
            return title or query
        matched = pick_matching_name(await self.header_candidates(), query)
        if matched:
            return matched
        # Clicking the sidebar often opens the right chat while the header
        # first paints "Profile details" (UI chrome). Don't abort.
        if clicked and await self.main_open():
            return title if title and not is_chrome_label(title) else query
        if title and not is_chrome_label(title) and not names_match(title, query):
            raise ChatNotFound(
                f"Opened '{title}', which does not match '{query}'. Refusing to continue."
            )
        return title or query

    async def _click_listed_chat(self, page, query: str) -> bool:
        names = await self.list_chat_names()
        matched = pick_matching_name(names, query)
        if not matched:
            # Last resort: click a visible row that contains the query text.
            pane = page.locator(
                "#pane-side, [aria-label='Chat list'], [data-testid='chat-list'], #side"
            )
            loc = pane.get_by_text(query, exact=False).first
            try:
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click(timeout=5_000)
                    return True
            except Exception:  # noqa: BLE001
                return False
            return False
        return await self._click_name(page, matched)

    async def _click_name(self, page, matched: str) -> bool:
        pane = page.locator(
            "#pane-side, [aria-label='Chat list'], [data-testid='chat-list'], #side"
        )
        attempts = [
            pane.locator("[role='listitem']").filter(has_text=matched).first,
            pane.get_by_title(matched, exact=True).first,
            pane.get_by_text(matched, exact=False).first,
        ]
        for loc in attempts:
            try:
                if await loc.count() == 0:
                    continue
                await loc.click(timeout=5_000)
                return True
            except Exception:  # noqa: BLE001
                continue
        return False

    async def _search_and_open(self, page, query: str) -> bool:
        icon = await first_visible(page, SEARCH_ICON, timeout_ms=3_000)
        if icon is not None:
            try:
                await icon.click()
                await asyncio.sleep(0.35)
            except Exception:  # noqa: BLE001
                pass

        search = await first_visible(page, SEARCH_BOX, timeout_ms=8_000)
        if search is None:
            return False

        await search.click()
        await asyncio.sleep(0.2)
        try:
            await search.fill("")
        except Exception:  # noqa: BLE001 — contenteditable may not support fill
            await page.keyboard.press("Meta+A")
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
        await page.keyboard.insert_text(query)
        await asyncio.sleep(1.4)

        if await self._click_listed_chat(page, query):
            return True
        return await self._click_name(page, query)
