"""Isolated Playwright session for Gmail Web.

Cookies live in `user_data_dir` (treat like a password). Separate from the
generic browser and WhatsApp profiles.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ribhus.channels.gmail_web.selectors import (
    GMAIL_URL,
    LOGIN_HINT,
    LOGGED_IN,
    any_visible,
)


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

        page = await self.ensure()
        if "mail.google.com" not in (page.url or ""):
            _status("Opening Gmail…")
            await page.goto(GMAIL_URL, wait_until="domcontentloaded", timeout=60_000)

        if await any_visible(page, LOGGED_IN, timeout_ms=10_000):
            _status("Already logged in to Gmail.")
            return page

        needs_login = await any_visible(page, LOGIN_HINT, timeout_ms=4_000)
        if needs_login and not self.headed:
            raise RuntimeError(
                "Gmail needs a Google sign-in, which requires a headed browser. "
                "Set RIBHUS_EMAIL_HEADED=true, sign in once in the Chromium window, "
                "and retry."
            )

        if needs_login:
            _status(
                "Sign in to Google in the Chromium window "
                f"(waiting up to {int(self.login_timeout)}s)…"
            )
        else:
            _status("Waiting for Gmail inbox to load…")

        timeout_ms = int(self.login_timeout * 1000)
        logged = await any_visible(page, LOGGED_IN, timeout_ms=timeout_ms)
        if logged:
            _status("Logged in to Gmail.")
            return page

        raise RuntimeError(
            "Gmail did not become ready in time. Open the headed window, "
            "complete Google sign-in (and 2FA if asked), then retry."
        )

    async def login_state(self) -> dict[str, object]:
        info: dict[str, object] = {**self.snapshot()}
        if self._page is None:
            info["logged_in"] = False
            info["login_prompt"] = False
            return info
        page = self._page
        info["url"] = page.url
        info["logged_in"] = await any_visible(page, LOGGED_IN, timeout_ms=1_500)
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
