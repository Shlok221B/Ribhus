"""Isolated Playwright session for Gmail Web.

Cookies live in `user_data_dir` (treat like a password). Separate from the
generic browser and WhatsApp profiles.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

from ribhus.channels.gmail_web.selectors import (
    GMAIL_URL,
    LOGIN_HINT,
    LOGGED_IN,
    any_visible,
)

def gmail_url_is_inbox(url: str) -> bool:
    """True once Gmail itself is open, including after 2FA and recovery screens."""
    raw = (url or "").lower()
    if "mail.google.com" not in raw or "/mail/" not in raw:
        return False
    blocked = ("servicelogin", "/signin", "accounts.google.com", "/challenge/")
    return not any(part in raw for part in blocked)


def _page_url(page: Any) -> str:
    try:
        return str(page.url or "")
    except Exception:  # noqa: BLE001
        return ""


def _needs_google_signin(url: str) -> bool:
    raw = (url or "").lower()
    return "accounts.google.com" in raw or "signin" in raw


def brave_executable() -> str | None:
    """Brave binary for Gmail, so Playwright's own Chromium download is optional."""
    override = os.environ.get("RIBHUS_BRAVE_PATH", "").strip()
    candidates = [override] if override else []
    home = Path.home()
    candidates.extend(
        [
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            str(home / "Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
            "/usr/bin/brave-browser",
            "/usr/bin/brave",
        ]
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


class GmailSession:
    """Persistent Chromium context dedicated to mail.google.com."""

    def __init__(
        self,
        *,
        user_data_dir: Path,
        headed: bool = True,
        login_timeout: float = 180.0,
    ) -> None:
        self.user_data_dir = user_data_dir
        self.headed = headed
        self.login_timeout = login_timeout
        self._playwright = None
        self._context = None
        self._page = None

    @property
    def page(self) -> Any:
        return self._page

    def snapshot(self) -> dict[str, object]:
        return {
            "started": self._page is not None,
            "headed": self.headed,
            "profile": str(self.user_data_dir),
            "login_timeout": self.login_timeout,
        }

    async def ensure(self):
        if self._page is not None:
            try:
                # Recover if the tab crashed / was closed.
                _ = self._page.url
                return self._page
            except Exception:  # noqa: BLE001
                self._page = None
                try:
                    if self._context is not None:
                        await self._context.close()
                except Exception:  # noqa: BLE001
                    pass
                self._context = None
                if self._playwright is not None:
                    try:
                        await self._playwright.stop()
                    except Exception:  # noqa: BLE001
                        pass
                    self._playwright = None

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Run: "
                "`uv sync` then `uv run playwright install chromium`"
            ) from exc

        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        brave = brave_executable()
        launch_kwargs: dict[str, Any] = {
            "user_data_dir": str(self.user_data_dir),
            "headless": not self.headed,
            "viewport": {"width": 1280, "height": 900},
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if brave:
            launch_kwargs["executable_path"] = brave
        try:
            self._context = await self._playwright.chromium.launch_persistent_context(
                **launch_kwargs
            )
        except Exception as exc:
            await self._playwright.stop()
            self._playwright = None
            message = str(exc)
            if "Executable doesn't exist" in message or "playwright install" in message.lower():
                raise RuntimeError(
                    "Gmail needs Brave, or Playwright's Chromium. "
                    "Install Brave, or run: `uv run playwright install chromium`"
                ) from exc
            raise RuntimeError(f"Failed to start Gmail browser: {exc}") from exc

        self._page = (
            self._context.pages[0]
            if self._context.pages
            else await self._context.new_page()
        )
        return self._page

    async def go_inbox(self) -> Any:
        """Navigate to inbox (best-effort cleanup after compose/send)."""
        page = await self.ensure_logged_in()
        try:
            await page.goto(GMAIL_URL, wait_until="domcontentloaded", timeout=45_000)
            await any_visible(page, LOGGED_IN, timeout_ms=8_000)
        except Exception:  # noqa: BLE001
            pass
        return page

    async def ensure_logged_in(self, *, on_status=None):
        def _status(message: str) -> None:
            if on_status is not None:
                on_status(message)

        _status(
            "Sign in to Google in the Brave window "
            f"(waiting up to {int(self.login_timeout)}s)…"
        )
        deadline = time.monotonic() + self.login_timeout
        last_urls: list[str] = []
        opened = False
        while time.monotonic() < deadline:
            await self.ensure()
            signed_in = await self._signed_in_page()
            if signed_in is not None:
                self._page = signed_in
                try:
                    await signed_in.bring_to_front()
                except Exception:  # noqa: BLE001
                    pass
                _status("Logged in to Gmail.")
                return signed_in

            pages = self._open_pages()
            last_urls = [_page_url(page) for page in pages]
            if any(_needs_google_signin(url) for url in last_urls) and not self.headed:
                raise RuntimeError(
                    "Gmail needs a Google sign-in, which requires a headed browser. "
                    "Set RIBHUS_EMAIL_HEADED=true, sign in once in the Brave window, "
                    "and retry."
                )
            if not opened and not any("google." in url for url in last_urls):
                opened = True
                target = self._page or (pages[0] if pages else None)
                if target is not None:
                    _status("Opening Gmail…")
                    try:
                        await target.goto(
                            GMAIL_URL, wait_until="domcontentloaded", timeout=60_000
                        )
                    except Exception:  # noqa: BLE001
                        opened = False
            await asyncio.sleep(1)

        shown = ", ".join(url[:140] for url in last_urls if url) or "(no Brave window)"
        raise RuntimeError(
            "Gmail is still not in the inbox. Finish sign-in, 2FA, or the recovery "
            f"prompts in the Brave window, then retry. Last page: {shown}"
        )

    def _open_pages(self) -> list[Any]:
        if self._context is None:
            return []
        try:
            return list(self._context.pages)
        except Exception:  # noqa: BLE001
            return []

    async def _signed_in_page(self) -> Any | None:
        for page in self._open_pages():
            url = _page_url(page)
            if gmail_url_is_inbox(url):
                return page
            if "mail.google.com" not in url:
                continue
            if await any_visible(page, LOGGED_IN, timeout_ms=800):
                return page
        return None

    async def login_state(self) -> dict[str, object]:
        info: dict[str, object] = {**self.snapshot()}
        if self._page is None:
            info["logged_in"] = False
            info["login_prompt"] = False
            return info
        page = self._page
        url = _page_url(page)
        info["url"] = url
        info["logged_in"] = gmail_url_is_inbox(url) or await any_visible(
            page, LOGGED_IN, timeout_ms=1_500
        )
        info["login_prompt"] = (
            False
            if info["logged_in"]
            else await any_visible(page, LOGIN_HINT, timeout_ms=1_500)
        )
        return info

    async def close(self) -> None:
        context, playwright = self._context, self._playwright
        self._context = None
        self._page = None
        self._playwright = None
        if context is not None:
            try:
                await context.close()
            except Exception:  # noqa: BLE001
                pass
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception:  # noqa: BLE001
                pass
        try:
            from ribhus.channels.browser_cleanup import force_release_profile

            force_release_profile(self.user_data_dir)
        except Exception:  # noqa: BLE001
            return
