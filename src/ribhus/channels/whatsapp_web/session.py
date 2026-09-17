"""Isolated Playwright session for WhatsApp Web.

Credentials live only in `user_data_dir` (treat it like a password). This is
separate from the generic browser profile so WhatsApp cookies never mix with
ordinary browsing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ribhus.channels.whatsapp_web.selectors import (
    CHAT_ROWS,
    LOGGED_IN,
    QR_CODE,
    WHATSAPP_URL,
    any_visible,
)


class WhatsAppSession:
    """Persistent Chromium context dedicated to web.whatsapp.com."""

    def __init__(
        self,
        *,
        user_data_dir: Path,
        headed: bool = True,
        login_timeout: float = 120.0,
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
            return self._page

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Run: "
                "`uv sync` then `uv run playwright install chromium`"
            ) from exc

        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        try:
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.user_data_dir),
                headless=not self.headed,
                viewport={"width": 1280, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception as exc:
            await self._playwright.stop()
            self._playwright = None
            message = str(exc)
            if "Executable doesn't exist" in message or "playwright install" in message.lower():
                raise RuntimeError(
                    "Chromium is not installed for Playwright. "
                    "Run: `uv run playwright install chromium`"
                ) from exc
            raise RuntimeError(f"Failed to start WhatsApp browser: {exc}") from exc

        self._page = (
            self._context.pages[0]
            if self._context.pages
            else await self._context.new_page()
        )
        return self._page

    async def ensure_logged_in(self):
        page = await self.ensure()
        if not page.url.startswith(WHATSAPP_URL):
            await page.goto(WHATSAPP_URL, wait_until="domcontentloaded", timeout=45_000)

        if await any_visible(page, LOGGED_IN, timeout_ms=8_000):
            await any_visible(page, CHAT_ROWS, timeout_ms=15_000)
            return page

        qr = await any_visible(page, QR_CODE, timeout_ms=4_000)
        if qr and not self.headed:
            raise RuntimeError(
                "WhatsApp Web needs a QR scan, which requires a headed browser. "
                "Set RIBHUS_WHATSAPP_HEADED=true and scan the QR code with your phone."
            )

        timeout_ms = int(self.login_timeout * 1000)
        logged = await any_visible(page, LOGGED_IN, timeout_ms=timeout_ms)
        if logged:
            await any_visible(page, CHAT_ROWS, timeout_ms=15_000)
            return page

        raise RuntimeError(
            "WhatsApp Web did not become ready in time. "
            "Open the headed window, scan the QR code with your phone, "
            "and retry. Ribhus does not promise the session will stay valid."
        )

    async def login_state(self) -> dict[str, object]:
        """Inspect the current page without waiting for a QR scan."""
        info: dict[str, object] = {**self.snapshot()}
        if self._page is None:
            info["logged_in"] = False
            info["qr_visible"] = False
            return info
        page = self._page
        info["url"] = page.url
        info["logged_in"] = await any_visible(page, LOGGED_IN, timeout_ms=1_500)
        info["qr_visible"] = (
            False
            if info["logged_in"]
            else await any_visible(page, QR_CODE, timeout_ms=1_500)
        )
        return info

    async def close(self) -> None:
        if self._context is not None:
            await self._context.close()
            self._context = None
            self._page = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
