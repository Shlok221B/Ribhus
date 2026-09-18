"""Gmail Web DOM selectors.

Gmail's UI churns often. Prefer role/aria labels over hashed class names.
"""

from __future__ import annotations

from typing import Any

GMAIL_URL = "https://mail.google.com/mail/u/0/#inbox"
GMAIL_HOSTS = frozenset(
    {
        "mail.google.com",
        "gmail.com",
        "www.gmail.com",
        "accounts.google.com",
    }
)

LOGGED_IN = [
    "div[role='main']",
    "div[aria-label='Inbox']",
    "div[data-tooltip='Inbox']",
    "tr.zA",
    "div[role='navigation']",
]

INBOX_ROWS = [
    "div[role='main'] tr.zA",
    "div[role='main'] tr[role='row']",
    "table.F tr.zA",
]

LOGIN_HINT = [
    "input[type='email']",
    "#identifierId",
    "input[name='identifier']",
    "text=Sign in",
]

SEARCH_BOX = [
    "input[aria-label='Search mail']",
    "form[role='search'] input",
    "input[name='q']",
]

COMPOSE_BUTTON = [
    "div[role='button'][gh='cm']",
    "div[role='button'][aria-label*='Compose']",
    "div[role='button'][data-tooltip*='Compose']",
    "div.T-I.T-I-KE.L3",
]

COMPOSE_DIALOG = [
    "div[role='dialog']",
    "div.nH.Hd",
    "div.M9",
    "div.AD",
]

TO_FIELD = [
    # Modern People Kit / recipients chip input
    "div[role='dialog'] input[aria-label*='To']",
    "div[role='dialog'] textarea[aria-label*='To']",
    "input[aria-label='To recipients']",
    "input[aria-label*='To recipient']",
    "div[aria-label='To recipients'] input",
    "div[aria-label='To'] input",
    "div[aria-label^='To'][role='textbox']",
    "div[role='dialog'] div[aria-label^='To']",
    "textarea[name='to']",
    "input[name='to']",
    "textarea[aria-label*='To']",
    "div.agP.aFw input",  # peoplekit
    "div[peoplekit-id] input",
]

SUBJECT_FIELD = [
    "div[role='dialog'] input[name='subjectbox']",
    "div[role='dialog'] input[aria-label*='Subject']",
    "input[name='subjectbox']",
    "input[aria-label='Subject']",
    "input[aria-label*='Subject']",
]

BODY_FIELD = [
    "div[role='dialog'] div[aria-label='Message Body']",
    "div[role='dialog'] div[aria-label*='Message Body']",
    "div[aria-label='Message Body']",
    "div[role='textbox'][aria-label*='Message Body']",
    "div[contenteditable='true'][aria-label*='Message Body']",
    "div[role='dialog'] div[contenteditable='true'][aria-label*='Body']",
    "div.Am.Al.editable",
    "div[role='dialog'] div[g_editable='true']",
]

SEND_BUTTON = [
    # Prefer real compose Send (not "Send feedback" / "Send invite")
    "div[role='dialog'] div[role='button'][aria-label^='Send']",
    "div[role='dialog'] div[role='button'][data-tooltip^='Send']",
    "div[role='button'][aria-label^='Send ‪']",  # "Send (⌘Enter)"
    "div[role='button'][data-tooltip^='Send ‪']",
    "div[role='button'][aria-label='Send']",
    "div[role='button'][data-tooltip='Send']",
    "div.T-I.J-J5-Ji.aoO.v7.T-I-atl.L3",  # classic blue Send
    "div.T-I.J-J5-Ji.aoO",
]

REPLY_BUTTON = [
    "div[role='button'][aria-label='Reply']",
    "span[role='link'][data-tooltip='Reply']",
    "div[data-tooltip='Reply']",
]

THREAD_SUBJECT = [
    "h2.hP",
    "h2[data-thread-perm-id]",
    "div[role='main'] h2",
]


async def any_visible(page: Any, selectors: list[str], *, timeout_ms: int = 3_000) -> bool:
    return await first_visible(page, selectors, timeout_ms=timeout_ms) is not None


async def first_visible(page: Any, selectors: list[str], *, timeout_ms: int = 5_000):
    """Return the first visible locator matching any selector.

    Searches the main page and child frames (Gmail sometimes nests compose).
    """
    scopes: list[Any] = [page]
    try:
        frames = list(getattr(page, "frames", []) or [])
        for frame in frames:
            if frame is not page and frame not in scopes:
                scopes.append(frame)
    except Exception:  # noqa: BLE001
        pass

    per = max(400, timeout_ms // max(1, len(selectors) * max(1, len(scopes))))
    for scope in scopes:
        for selector in selectors:
            try:
                loc = scope.locator(selector).first
                await loc.wait_for(state="visible", timeout=per)
                return loc
            except Exception:  # noqa: BLE001
                continue
    return None
