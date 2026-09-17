"""WhatsApp Web DOM selectors.

The WhatsApp Web UI changes without notice. Prefer structural selectors
(#side, #main, #pane-side, contenteditable, role=listitem) over hashed classes.
"""

from __future__ import annotations

from typing import Any

WHATSAPP_URL = "https://web.whatsapp.com"
WHATSAPP_HOSTS = frozenset(
    {
        "web.whatsapp.com",
        "whatsapp.com",
        "www.whatsapp.com",
        "api.whatsapp.com",
    }
)

LOGGED_IN = [
    "div[aria-label='Chat list']",
    "#pane-side",
    "div[data-testid='chat-list']",
    "[role='listitem']",
    "#side",
]

CHAT_ROWS = [
    "[aria-label='Chat list'] [role='listitem']",
    "#pane-side [role='listitem']",
    "#pane-side [role='row']",
    "#side [role='listitem']",
    "[data-testid='chat-list'] [role='listitem']",
    "#pane-side span[title]",
]

QR_CODE = [
    "canvas[aria-label*='QR']",
    "div[data-testid='qrcode']",
    "div[aria-label*='QR'] canvas",
    "canvas[aria-label*='Scan']",
]

SEARCH_ICON = [
    "button[aria-label='Search or start new chat']",
    "div[aria-label='Search or start new chat']",
    "button[aria-label*='Search or start']",
    "button[aria-label='Search']",
    "[data-icon='search']",
    "[data-icon='search-refreshed']",
    "[data-icon='search-refreshed-thin']",
]

SEARCH_BOX = [
    "[aria-label='Search input text']",
    "[aria-label='Search input text box']",
    "[aria-label*='Search input']",
    "div[role='textbox'][aria-label*='Search']",
    "#side [contenteditable='true']",
    "#pane-side [contenteditable='true']",
    "div[contenteditable='true'][data-tab='3']",
    "div[title='Search input text']",
    "[data-testid='chat-list-search'] [contenteditable='true']",
    "header [contenteditable='true']",
]

CHAT_LIST = [
    "div[aria-label='Chat list']",
    "#pane-side",
    "div[data-testid='chat-list']",
    "#side",
]

MAIN_PANEL = ["#main"]

COMPOSE_BOX = [
    "#main footer [contenteditable='true']",
    "footer [contenteditable='true'][data-tab='10']",
    "footer [contenteditable='true']",
    "div[aria-label='Type a message']",
    "div[aria-placeholder='Type a message']",
    "#main [contenteditable='true'][role='textbox']",
]

SEND_BUTTON = [
    "#main button[aria-label='Send']",
    "button[aria-label='Send']",
    "span[data-icon='send']",
    "[data-testid='send']",
]

CHAT_HEADER_TITLE = [
    "#main header span[title]",
    "#main header [data-testid='conversation-title']",
    "#main header span[dir='auto']",
    "#main header [role='button'] span[dir='auto']",
    "#main header h2",
    "#main header div[title]",
]


async def first_visible(page: Any, selectors: list[str], timeout_ms: int = 8_000):
    """Return the first *visible* locator matching any selector, or None."""
    if not selectors:
        return None
    combined = ", ".join(selectors)
    loc = page.locator(combined)
    try:
        await loc.first.wait_for(state="attached", timeout=timeout_ms)
    except Exception:  # noqa: BLE001
        return None
    count = await loc.count()
    for i in range(min(count, 40)):
        item = loc.nth(i)
        try:
            if await item.is_visible():
                return item
        except Exception:  # noqa: BLE001
            continue
    return None


async def any_visible(page: Any, selectors: list[str], timeout_ms: int = 3_000) -> bool:
    loc = await first_visible(page, selectors, timeout_ms=timeout_ms)
    return loc is not None
