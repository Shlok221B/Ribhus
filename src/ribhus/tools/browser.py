from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ribhus.channels.gmail_web.selectors import GMAIL_HOSTS
from ribhus.channels.whatsapp_web.selectors import WHATSAPP_HOSTS
from ribhus.policy.levels import RiskLevel
from ribhus.tools.base import Tool
from ribhus.tools.browser_snapshot import (
    format_snapshot,
    install_dialog_hooks,
    normalize_ref,
    read_js_dialogs,
    set_dialog_defaults,
    stamp_interactive,
)


class DomainNotAllowed(Exception):
    pass


class RateLimited(Exception):
    pass


def _channel_host(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    if host in WHATSAPP_HOSTS or host.endswith(".whatsapp.com"):
        return "whatsapp"
    if host in GMAIL_HOSTS:
        return "gmail"
    return None


class BrowserSession:
    """Playwright Chromium session — launched locally or attached via CDP."""

    def __init__(
        self,
        *,
        user_data_dir: Path,
        headed: bool = False,
        allowlist: list[str] | None = None,
        rate_limit_per_minute: int = 30,
        cdp_url: str | None = None,
    ) -> None:
        self.user_data_dir = user_data_dir
        self.headed = headed
        self.allowlist = [d.lower().lstrip(".") for d in (allowlist or []) if d.strip()]
        self.rate_limit_per_minute = rate_limit_per_minute
        self.cdp_url = (cdp_url or "").strip() or None
        self._playwright = None
        self._browser = None  # CDP-connected browser
        self._context = None
        self._page = None
        self._cdp_mode = False
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._native_dialogs: list[dict[str, str]] = []
        self._console_logs: list[str] = []

    @property
    def page(self) -> Any:
        return self._page

    def snapshot_meta(self) -> dict[str, object]:
        return {
            "started": self._page is not None,
            "headed": self.headed,
            "cdp_mode": self._cdp_mode,
            "cdp_url": self.cdp_url,
            "profile": str(self.user_data_dir),
        }

    def check_url(self, url: str) -> None:
        host = (urlparse(url).hostname or "").lower()
        if not host:
            raise DomainNotAllowed(f"Invalid URL (no host): {url}")
        channel = _channel_host(url)
        if channel == "whatsapp":
            raise DomainNotAllowed(
                "The generic browser tool cannot open WhatsApp. "
                "Use whatsapp_open_chat / whatsapp_read / whatsapp_send so "
                "approval, rate limits, and the kill switch apply."
            )
        if channel == "gmail" or host in GMAIL_HOSTS:
            raise DomainNotAllowed(
                "The generic browser tool cannot open Gmail. "
                "Use email_list / email_reply / email_send so "
                "approval, rate limits, and the kill switch apply."
            )
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

    def _on_native_dialog(self, dialog: Any) -> None:
        try:
            self._native_dialogs.append(
                {
                    "type": str(getattr(dialog, "type", "") or "dialog"),
                    "message": str(getattr(dialog, "message", "") or ""),
                }
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            asyncio.get_running_loop().create_task(dialog.dismiss())
        except RuntimeError:
            try:
                asyncio.ensure_future(dialog.dismiss())
            except Exception:  # noqa: BLE001
                pass

    def _on_console(self, msg: Any) -> None:
        try:
            text = f"{msg.type}: {msg.text}"
            self._console_logs.append(text[:500])
            if len(self._console_logs) > 80:
                self._console_logs = self._console_logs[-80:]
        except Exception:  # noqa: BLE001
            return

    async def _wire_page(self, page: Any) -> Any:
        page.on("dialog", self._on_native_dialog)
        page.on("console", self._on_console)
        await install_dialog_hooks(page)
        return page

    async def ensure(self):
        if self._page is not None:
            return self._page
        if self.cdp_url:
            return await self.connect(self.cdp_url)
        return await self._launch_local()

    async def _launch_local(self):
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

        self._cdp_mode = False
        self._page = (
            self._context.pages[0]
            if self._context.pages
            else await self._context.new_page()
        )
        await self._wire_page(self._page)
        return self._page

    async def connect(self, cdp_url: str):
        """Attach to a running Chromium-family browser over CDP."""
        endpoint = (cdp_url or "").strip()
        if not endpoint:
            raise RuntimeError(
                "CDP URL is empty. Pass url=http://127.0.0.1:9222 or set "
                "RIBHUS_BROWSER_CDP_URL."
            )
        if not endpoint.startswith(("http://", "https://", "ws://", "wss://")):
            endpoint = "http://" + endpoint

        # Replace any existing session first.
        await self.close()

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Run: "
                "`uv sync` then `uv run playwright install chromium`"
            ) from exc

        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(endpoint)
        except Exception as exc:
            await self._playwright.stop()
            self._playwright = None
            raise RuntimeError(
                f"Failed to connect over CDP to {endpoint}: {exc}. "
                "Start Chrome with "
                "--remote-debugging-port=9222 "
                "--user-data-dir=/tmp/ribhus-chrome-debug "
                "(dedicated profile required on Chrome 136+)."
            ) from exc

        contexts = self._browser.contexts
        self._context = contexts[0] if contexts else await self._browser.new_context()
        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        self._cdp_mode = True
        self.cdp_url = endpoint
        await self._wire_page(self._page)
        return self._page

    async def close(self) -> None:
        """Close local browser, or disconnect CDP (does not quit the user's Chrome)."""
        self._page = None
        try:
            if self._cdp_mode:
                if self._browser is not None:
                    await self._browser.close()
            elif self._context is not None:
                await self._context.close()
        except Exception:  # noqa: BLE001
            pass
        self._browser = None
        self._context = None
        self._cdp_mode = False
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:  # noqa: BLE001
                pass
            self._playwright = None


class BrowserTool(Tool):
    name = "browser"
    description = (
        "Control Chromium (local Playwright or CDP-attached Chrome). "
        "Actions: open, snapshot, click, type, scroll, press, back, read, "
        "screenshot, screenshot_ask, extract, console, dialog, connect, "
        "status, close. "
        "Preferred flow: open → snapshot → click/type with ref=@eN → "
        "snapshot again. Prefer refs over CSS when possible. "
        "connect attaches to a running Chrome at a CDP URL "
        "(e.g. http://127.0.0.1:9222). "
        "screenshot_ask analyzes the page with vision."
    )
    risk_level = RiskLevel.MEDIUM.value

    def __init__(
        self,
        session: BrowserSession,
        *,
        screenshot_dir: Path,
        vision_analyze=None,
    ) -> None:
        self.session = session
        self.screenshot_dir = screenshot_dir
        self.vision_analyze = vision_analyze

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "open",
                        "snapshot",
                        "click",
                        "type",
                        "scroll",
                        "press",
                        "back",
                        "read",
                        "screenshot",
                        "screenshot_ask",
                        "extract",
                        "console",
                        "dialog",
                        "connect",
                        "status",
                        "close",
                    ],
                    "description": "Browser action to perform",
                },
                "url": {
                    "type": "string",
                    "description": "URL for open, or CDP endpoint for connect",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS selector for click/type/extract",
                },
                "ref": {
                    "type": "string",
                    "description": "Snapshot ref like @e3 for click/type",
                },
                "text": {
                    "type": "string",
                    "description": "Text to type, button/link text, or key for press",
                },
                "key": {
                    "type": "string",
                    "description": "Key for press (Enter, Tab, Escape, ArrowDown, …)",
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
                "full": {
                    "type": "boolean",
                    "description": "snapshot: include page text (default false)",
                    "default": False,
                },
                "expression": {
                    "type": "string",
                    "description": "JavaScript for console action (optional)",
                },
                "dialog_action": {
                    "type": "string",
                    "enum": ["accept", "dismiss", "list"],
                    "description": "dialog: accept/dismiss next JS confirm/prompt, or list",
                },
                "question": {
                    "type": "string",
                    "description": "Question for screenshot_ask",
                },
            },
            "required": ["action"],
        }

    def risk_for_arguments(self, arguments: dict[str, Any]) -> RiskLevel:
        action = str(arguments.get("action", "")).lower()
        if action in {"click", "type", "press", "dialog", "console"}:
            return RiskLevel.HIGH
        if action in {"close", "status", "snapshot", "back"}:
            return RiskLevel.LOW if action in {"close", "status"} else RiskLevel.MEDIUM
        if action in {
            "open",
            "read",
            "screenshot",
            "screenshot_ask",
            "extract",
            "scroll",
            "connect",
        }:
            return RiskLevel.MEDIUM
        return RiskLevel.MEDIUM

    def _guard_page_url(self, page: Any) -> str | None:
        channel = _channel_host(page.url or "")
        if channel == "whatsapp":
            return (
                "Error: generic browser tool cannot control WhatsApp Web. "
                "Use whatsapp_open_chat / whatsapp_read / whatsapp_send."
            )
        if channel == "gmail":
            return (
                "Error: generic browser tool cannot control Gmail. "
                "Use email_list / email_reply / email_send."
            )
        return None

    async def _locator_for_target(self, page: Any, arguments: dict[str, Any]):
        ref = normalize_ref(arguments.get("ref"))
        selector = arguments.get("selector")
        if ref:
            loc = page.locator(f'[data-ribhus-ref="{ref}"]')
            if await loc.count() == 0:
                await stamp_interactive(page)
                loc = page.locator(f'[data-ribhus-ref="{ref}"]')
            if await loc.count() == 0:
                return None, f"ref=@{ref} (not found — run snapshot)"
            return loc.first, f"ref=@{ref}"
        if selector:
            return page.locator(str(selector)).first, f"selector={selector}"
        return None, None

    async def execute(self, arguments: dict[str, Any]) -> str:
        action = str(arguments.get("action", "")).lower().strip()
        if not action:
            return "Error: action is required"

        try:
            if action == "status":
                meta = self.session.snapshot_meta()
                url = ""
                if self.session.page is not None:
                    try:
                        url = self.session.page.url
                    except Exception:  # noqa: BLE001
                        url = ""
                return (
                    f"started={meta['started']} cdp_mode={meta['cdp_mode']} "
                    f"headed={meta['headed']}\n"
                    f"cdp_url={meta['cdp_url'] or '(none)'}\n"
                    f"profile={meta['profile']}\n"
                    f"page_url={url or '(none)'}"
                )

            if action == "close":
                await self.session.close()
                return "Browser closed (CDP disconnect leaves your Chrome running)."

            if action == "connect":
                endpoint = str(arguments.get("url") or self.session.cdp_url or "").strip()
                if not endpoint:
                    return (
                        "Error: url is required for connect "
                        "(e.g. http://127.0.0.1:9222), or set RIBHUS_BROWSER_CDP_URL."
                    )
                page = await self.session.connect(endpoint)
                title = ""
                try:
                    title = await page.title()
                except Exception:  # noqa: BLE001
                    pass
                return (
                    f"Connected over CDP to {self.session.cdp_url}\n"
                    f"URL: {page.url}\nTitle: {title}"
                )

            page = await self.session.ensure()
            if action != "open":
                blocked = self._guard_page_url(page)
                if blocked:
                    return blocked

            if action == "open":
                url = str(arguments.get("url", "")).strip()
                if not url:
                    return "Error: url is required for open"
                if not url.startswith(("http://", "https://")):
                    url = "https://" + url
                self.session.check_url(url)
                await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                await install_dialog_hooks(page)
                title = await page.title()
                stamped = await stamp_interactive(page)
                preview = format_snapshot(stamped, full=False)
                return f"Opened {page.url}\nTitle: {title}\n\n{preview}"

            if action == "snapshot":
                await install_dialog_hooks(page)
                stamped = await stamp_interactive(page)
                full = bool(arguments.get("full"))
                if full:
                    try:
                        body = await page.inner_text("body")
                    except Exception:  # noqa: BLE001
                        body = ""
                    stamped["body"] = body
                pending = list(self.session._native_dialogs)
                self.session._native_dialogs.clear()
                js_dialogs = await read_js_dialogs(page)
                text = format_snapshot(stamped, full=full)
                if pending or js_dialogs:
                    text += "\n\nDialogs seen:\n"
                    for d in pending + js_dialogs:
                        text += f"  - {d.get('type')}: {d.get('message')}\n"
                return text

            if action == "click":
                loc, label = await self._locator_for_target(page, arguments)
                text = arguments.get("text")
                if loc is not None:
                    await loc.click(timeout=15_000)
                    return f"Clicked {label}\nURL: {page.url}"
                if label and "not found" in str(label):
                    return f"Error: {label}"
                if text:
                    await page.get_by_text(str(text), exact=False).first.click(
                        timeout=15_000
                    )
                    return f"Clicked text: {text}\nURL: {page.url}"
                return "Error: provide ref (@eN), selector, or text for click"

            if action == "type":
                text = arguments.get("text")
                if text is None:
                    return "Error: text is required for type"
                loc, label = await self._locator_for_target(page, arguments)
                if loc is None:
                    if label and "not found" in str(label):
                        return f"Error: {label}"
                    return "Error: provide ref (@eN) or selector for type"
                clear = arguments.get("clear", True)
                if clear:
                    await loc.fill(str(text), timeout=15_000)
                else:
                    await loc.click(timeout=15_000)
                    await page.keyboard.type(str(text))
                return f"Typed into {label} ({len(str(text))} chars)"

            if action == "scroll":
                amount = int(arguments.get("amount") or 800)
                await page.mouse.wheel(0, amount)
                await asyncio.sleep(0.2)
                return f"Scrolled by {amount}px\nURL: {page.url}"

            if action == "press":
                key = str(arguments.get("key") or arguments.get("text") or "").strip()
                if not key:
                    return "Error: key is required for press (e.g. Enter, Tab, Escape)"
                await page.keyboard.press(key)
                return f"Pressed {key}\nURL: {page.url}"

            if action == "back":
                await page.go_back(wait_until="domcontentloaded", timeout=15_000)
                title = await page.title()
                return f"Back → {page.url}\nTitle: {title}"

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
                return (
                    f"Screenshot saved: {path}\n"
                    "Tip: call vision with this path (or omit path for latest shot)."
                )

            if action == "screenshot_ask":
                question = str(arguments.get("question") or "").strip()
                if not question:
                    return "Error: question is required for screenshot_ask"
                if self.vision_analyze is None:
                    return (
                        "Error: vision is not configured. "
                        "Take a screenshot then call the vision tool."
                    )
                self.screenshot_dir.mkdir(parents=True, exist_ok=True)
                path = self.screenshot_dir / f"shot_{int(time.time())}.png"
                await page.screenshot(path=str(path), full_page=False)
                answer = await self.vision_analyze(path, question)
                return f"Screenshot: {path}\nURL: {page.url}\n\n{answer}"

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
                    return (
                        f"Extracted {min(count, 30)}/{count} nodes "
                        f"for {selector}:\n{joined}"
                    )
                body = await page.inner_text("body")
                if len(body) > 12_000:
                    body = body[:12_000] + "\n...[truncated]"
                return f"URL: {page.url}\n\n{body}"

            if action == "console":
                expression = arguments.get("expression")
                if expression:
                    raw = await page.evaluate(str(expression))
                    text = repr(raw) if not isinstance(raw, str) else raw
                    if len(text) > 8_000:
                        text = text[:8_000] + "\n...[truncated]"
                    return f"console eval →\n{text}"
                logs = list(self.session._console_logs[-50:])
                if not logs:
                    return (
                        "No console messages yet. "
                        "Pass expression= to evaluate JS "
                        "(e.g. document.title)."
                    )
                return "Console:\n" + "\n".join(logs)

            if action == "dialog":
                dialog_action = str(
                    arguments.get("dialog_action") or arguments.get("text") or "list"
                ).lower()
                if dialog_action == "list":
                    pending = list(self.session._native_dialogs)
                    js_dialogs = await read_js_dialogs(page)
                    all_d = pending + js_dialogs
                    if not all_d:
                        return "No dialogs recorded."
                    lines = ["Dialogs:"]
                    for d in all_d:
                        lines.append(f"  - {d.get('type')}: {d.get('message')}")
                    return "\n".join(lines)
                accept = dialog_action in {"accept", "a", "yes", "ok"}
                prompt_text = str(arguments.get("text") or "") if accept else ""
                if dialog_action not in {"accept", "dismiss", "a", "yes", "ok", "cancel"}:
                    return "Error: dialog_action must be accept, dismiss, or list"
                await set_dialog_defaults(
                    page, accept=accept, prompt_text=prompt_text
                )
                return (
                    f"Next JS confirm/prompt will "
                    f"{'ACCEPT' if accept else 'DISMISS'}"
                    + (f" (prompt text set, {len(prompt_text)} chars)" if prompt_text else "")
                    + ". Native alert/confirm dialogs are auto-dismissed and listed "
                    "on snapshot."
                )

            return f"Error: unknown action '{action}'"
        except DomainNotAllowed as exc:
            return f"Error: {exc}"
        except RateLimited as exc:
            return f"Error: {exc}"
        except Exception as exc:  # noqa: BLE001
            return f"Error in browser.{action}: {exc}"


# Back-compat alias used incorrectly in older code paths
def _whatsapp_host(url: str) -> bool:
    return _channel_host(url) == "whatsapp"
