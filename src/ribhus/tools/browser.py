from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ribhus.policy.levels import RiskLevel
from ribhus.tools.base import Tool


class DomainNotAllowed(Exception):
    pass


class RateLimited(Exception):
    pass


class BrowserSession:
    """Isolated Playwright Chromium session for one agent run."""

    def __init__(
        self,
        *,
        user_data_dir: Path,
        headed: bool = False,
        allowlist: list[str] | None = None,
        rate_limit_per_minute: int = 30,
    ) -> None:
        self.user_data_dir = user_data_dir
        self.headed = headed
        self.allowlist = [d.lower().lstrip(".") for d in (allowlist or []) if d.strip()]
        self.rate_limit_per_minute = rate_limit_per_minute
        self._playwright = None
        self._context = None
        self._page = None
        self._hits: dict[str, list[float]] = defaultdict(list)

    def check_url(self, url: str) -> None:
        host = (urlparse(url).hostname or "").lower()
        if not host:
            raise DomainNotAllowed(f"Invalid URL (no host): {url}")
        if self.allowlist and not any(
            host == domain or host.endswith(f".{domain}") for domain in self.allowlist
        ):
            raise DomainNotAllowed(
                f"Domain '{host}' is not in the allowlist: {', '.join(self.allowlist)}"
            )
        self._rate_check(host)

    def _rate_check(self, host: str) -> None:
        now = time.monotonic()
        window = [t for t in self._hits[host] if now - t < 60]
        if len(window) >= self.rate_limit_per_minute:
            raise RateLimited(
                f"Rate limit exceeded for {host} "
                f"({self.rate_limit_per_minute}/min). Slow down."
            )
        window.append(now)
        self._hits[host] = window

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
                viewport={"width": 1280, "height": 720},
            )
        except Exception as exc:
            await self._playwright.stop()
            self._playwright = None
            message = str(exc)
            if "Executable doesn't exist" in message or "playwright install" in message.lower():
                raise RuntimeError(
                    "Chromium is not installed for Playwright. "
                    "Run this once in your terminal: "
                    "`uv run playwright install chromium`"
                ) from exc
            raise RuntimeError(f"Failed to start browser: {exc}") from exc

        self._page = (
            self._context.pages[0]
            if self._context.pages
            else await self._context.new_page()
        )
        return self._page

    async def close(self) -> None:
        if self._context is not None:
            await self._context.close()
            self._context = None
            self._page = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None


class BrowserTool(Tool):
    name = "browser"
    description = (
        "Control a ready Chromium browser (already installed — do not run "
        "playwright install). Actions: open, click, type, scroll, read, "
        "screenshot, extract, close. Prefer CSS selectors. "
        "Use read/extract after open to understand the page."
    )
    risk_level = RiskLevel.MEDIUM.value

    def __init__(
        self,
        session: BrowserSession,
        *,
        screenshot_dir: Path,
    ) -> None:
        self.session = session
        self.screenshot_dir = screenshot_dir

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "open",
                        "click",
                        "type",
                        "scroll",
                        "read",
                        "screenshot",
                        "extract",
                        "close",
                    ],
                    "description": "Browser action to perform",
                },
                "url": {
                    "type": "string",
                    "description": "URL for action=open",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS selector for click/type/extract",
                },
                "text": {
                    "type": "string",
                    "description": "Text to type, or button/link text to click",
                },
                "amount": {
                    "type": "integer",
                    "description": "Scroll amount in pixels (default 800)",
                    "default": 800,
                },
                "clear": {
                    "type": "boolean",
                    "description": "Clear field before typing (default true)",
                    "default": True,
                },
            },
            "required": ["action"],
        }

    def risk_for_arguments(self, arguments: dict[str, Any]) -> RiskLevel:
        action = str(arguments.get("action", "")).lower()
        if action in {"click", "type"}:
            return RiskLevel.HIGH
        if action == "close":
            return RiskLevel.LOW
        if action in {"open", "read", "screenshot", "extract", "scroll"}:
            return RiskLevel.MEDIUM
        return RiskLevel.MEDIUM

    async def execute(self, arguments: dict[str, Any]) -> str:
        action = str(arguments.get("action", "")).lower().strip()
        if not action:
            return "Error: action is required"

        try:
            if action == "close":
                await self.session.close()
                return "Browser closed."

            page = await self.session.ensure()

            if action == "open":
                url = str(arguments.get("url", "")).strip()
                if not url:
                    return "Error: url is required for open"
                if not url.startswith(("http://", "https://")):
                    url = "https://" + url
                self.session.check_url(url)
                await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                title = await page.title()
                return f"Opened {page.url}\nTitle: {title}"

            if action == "click":
                selector = arguments.get("selector")
                text = arguments.get("text")
                if selector:
                    await page.click(str(selector), timeout=15_000)
                    return f"Clicked selector: {selector}\nURL: {page.url}"
                if text:
                    await page.get_by_text(str(text), exact=False).first.click(
                        timeout=15_000
                    )
                    return f"Clicked text: {text}\nURL: {page.url}"
                return "Error: provide selector or text for click"

            if action == "type":
                selector = arguments.get("selector")
                text = arguments.get("text")
                if not selector or text is None:
                    return "Error: selector and text are required for type"
                clear = arguments.get("clear", True)
                loc = page.locator(str(selector)).first
                if clear:
                    await loc.fill(str(text), timeout=15_000)
                else:
                    await loc.type(str(text), timeout=15_000)
                return f"Typed into {selector} ({len(str(text))} chars)"

            if action == "scroll":
                amount = int(arguments.get("amount") or 800)
                await page.mouse.wheel(0, amount)
                await asyncio.sleep(0.3)
                return f"Scrolled by {amount}px\nURL: {page.url}"

            if action == "read":
                title = await page.title()
                body = await page.inner_text("body")
                if len(body) > 12_000:
                    body = body[:12_000] + "\n...[truncated]"
                return f"URL: {page.url}\nTitle: {title}\n\n{body}"

            if action == "screenshot":
                self.screenshot_dir.mkdir(parents=True, exist_ok=True)
                path = self.screenshot_dir / f"shot_{int(time.time())}.png"
                await page.screenshot(path=str(path), full_page=False)
                return f"Screenshot saved: {path}"

            if action == "extract":
                selector = arguments.get("selector")
                if selector:
                    loc = page.locator(str(selector))
                    count = await loc.count()
                    texts = []
                    for i in range(min(count, 30)):
                        t = (await loc.nth(i).inner_text()).strip()
                        if t:
                            texts.append(t)
                    joined = "\n---\n".join(texts) if texts else "(no text)"
                    if len(joined) > 12_000:
                        joined = joined[:12_000] + "\n...[truncated]"
                    return f"Extracted {min(count, 30)}/{count} nodes for {selector}:\n{joined}"
                # Fallback: main content-ish text
                body = await page.inner_text("body")
                if len(body) > 12_000:
                    body = body[:12_000] + "\n...[truncated]"
                return f"URL: {page.url}\n\n{body}"

            return f"Error: unknown action '{action}'"
        except DomainNotAllowed as exc:
            return f"Error: {exc}"
        except RateLimited as exc:
            return f"Error: {exc}"
        except Exception as exc:  # noqa: BLE001
            return f"Error in browser.{action}: {exc}"
