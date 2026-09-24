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
    resolve_ref_locator,
    resolve_selector_locator,
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
        self._wiring_page = False
        self._context_page_hooked = False

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
            "tab_count": len(self._context.pages) if self._context is not None else 0,
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
        if page is None:
            return page
        page.on("dialog", self._on_native_dialog)
        page.on("console", self._on_console)
        await install_dialog_hooks(page)
        return page

    def _hook_context_pages(self) -> None:
        """Adopt popups into the single active tab; drop extras."""
        if self._context is None or self._context_page_hooked:
            return
        self._context_page_hooked = True

        def _on_page(page: Any) -> None:
            if self._wiring_page:
                return
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            loop.create_task(self._adopt_new_page(page))

        self._context.on("page", _on_page)

    async def _adopt_new_page(self, page: Any) -> None:
        """When a site opens a tab (target=_blank), use it and close the old one."""
        if self._wiring_page or self._context is None:
            return
        self._wiring_page = True
        try:
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=15_000)
            except Exception:  # noqa: BLE001
                pass
            old = self._page
            await self._wire_page(page)
            self._page = page
            if old is not None and old != page:
                try:
                    await old.close()
                except Exception:  # noqa: BLE001
                    pass
            await self._collapse_extra_pages(keep=page)
        finally:
            self._wiring_page = False

    async def _collapse_extra_pages(self, *, keep: Any | None = None) -> Any:
        """Ensure exactly one tab — persistent profiles often restore many."""
        if self._context is None:
            return self._page
        pages = list(self._context.pages)
        if not pages:
            self._wiring_page = True
            try:
                page = await self._context.new_page()
                await self._wire_page(page)
                self._page = page
                return page
            finally:
                self._wiring_page = False

        if keep is None or keep not in pages:
            keep = self._page if self._page in pages else pages[-1]

        for page in pages:
            if page == keep:
                continue
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                continue

        self._page = keep
        return keep

    async def ensure(self):
        if self._page is not None:
            # Page may have been closed; recover.
            try:
                _ = self._page.url
                return await self._collapse_extra_pages(keep=self._page)
            except Exception:  # noqa: BLE001
                self._page = None
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
                args=["--no-first-run", "--no-default-browser-check"],
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
        self._context_page_hooked = False
        self._hook_context_pages()
        # Persistent context restores prior session tabs — keep one only.
        self._page = await self._collapse_extra_pages()
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
        self._cdp_mode = True
        self.cdp_url = endpoint
        self._context_page_hooked = False
        self._hook_context_pages()
        self._page = await self._collapse_extra_pages()
        await self._wire_page(self._page)
        return self._page

    async def close(self) -> None:
        """Close local browser, or disconnect CDP (does not quit the user's Chrome)."""
        cdp = self._cdp_mode
        browser, context, playwright = self._browser, self._context, self._playwright
        user_data_dir = self.user_data_dir
        self._page = None
        self._context_page_hooked = False
        self._browser = None
        self._context = None
        self._cdp_mode = False
        self._playwright = None
        try:
            if cdp:
                if browser is not None:
                    await browser.close()
            elif context is not None:
                await context.close()
        except Exception:  # noqa: BLE001
            pass
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception:  # noqa: BLE001
                pass
        # Local profile only — never force-kill a user's CDP Chrome.
        if not cdp:
            try:
                from ribhus.channels.browser_cleanup import force_release_profile

                force_release_profile(user_data_dir)
            except Exception:  # noqa: BLE001
                pass


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
        "wait / select / hover / reload for reliability; "
        "click/type work across same-origin iframes; "
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
                        "select",
                        "hover",
                        "wait",
                        "reload",
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
                    "description": "URL for open/wait, or CDP endpoint for connect",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS selector for click/type/select/hover/extract",
                },
                "ref": {
                    "type": "string",
                    "description": "Snapshot ref like @e3 for click/type/select/hover/wait",
                },
                "text": {
                    "type": "string",
                    "description": (
                        "Text to type; button/link text; select option label/value; "
                        "wait-until text; or key for press"
                    ),
                },
                "value": {
                    "type": "string",
                    "description": "select: option value (alternative to text/label)",
                },
                "key": {
                    "type": "string",
                    "description": "Key for press (Enter, Tab, Escape, ArrowDown, …)",
                },
                "until": {
                    "type": "string",
                    "enum": [
                        "load",
                        "networkidle",
                        "url",
                        "text",
                        "ref",
                        "timeout",
                    ],
                    "description": (
                        "wait: load|networkidle|url|text|ref|timeout "
                        "(default: text if text set, else load)"
                    ),
                },
                "timeout": {
                    "type": "integer",
                    "description": "wait timeout in ms (default 15000)",
                    "default": 15_000,
                },
                "hard": {
                    "type": "boolean",
                    "description": "reload: bypass cache when possible (default false)",
                    "default": False,
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
                "resnapshot": {
                    "type": "boolean",
                    "description": (
                        "After click/select/hover: include a fresh snapshot "
                        "(default true for click/select)"
                    ),
                    "default": True,
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
        if action in {"click", "type", "select", "press", "dialog", "console"}:
            return RiskLevel.HIGH
        if action in {"close", "status", "wait"}:
            return RiskLevel.LOW
        if action in {"snapshot", "back", "hover", "reload", "scroll"}:
            return RiskLevel.MEDIUM
        if action in {
            "open",
            "read",
            "screenshot",
            "screenshot_ask",
            "extract",
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

    async def _locator_for_target(
        self, page: Any, arguments: dict[str, Any], *, restamp: bool = True
    ):
        ref = normalize_ref(arguments.get("ref"))
        selector = arguments.get("selector")
        if ref:
            loc, label = await resolve_ref_locator(page, ref)
            if loc is None and restamp:
                await stamp_interactive(page)
                loc, label = await resolve_ref_locator(page, ref)
            return loc, label
        if selector:
            loc, label = await resolve_selector_locator(page, str(selector))
            return loc, label
        return None, None

    async def _fresh_snapshot(self, page: Any, *, full: bool = False) -> str:
        page = await self.session._collapse_extra_pages(keep=page)
        await install_dialog_hooks(page)
        stamped = await stamp_interactive(page)
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

    def _want_resnapshot(self, arguments: dict[str, Any], *, default: bool) -> bool:
        if "resnapshot" not in arguments:
            return default
        return bool(arguments.get("resnapshot"))

    async def _with_optional_snapshot(
        self,
        page: Any,
        header: str,
        arguments: dict[str, Any],
        *,
        default_resnapshot: bool = True,
    ) -> str:
        if not self._want_resnapshot(arguments, default=default_resnapshot):
            return f"{header}\nURL: {page.url}"
        await asyncio.sleep(0.2)
        snap = await self._fresh_snapshot(page)
        return f"{header}\n\n{snap}"

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
                page = await self.session._collapse_extra_pages(keep=page)
                # Same-tab navigation only — never open a fresh tab per URL.
                await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                page = await self.session._collapse_extra_pages(keep=page)
                await install_dialog_hooks(page)
                title = await page.title()
                stamped = await stamp_interactive(page)
                preview = format_snapshot(stamped, full=False)
                tabs = 0
                if self.session._context is not None:
                    tabs = len(self.session._context.pages)
                return (
                    f"Opened {page.url}\nTitle: {title}\nTabs: {tabs}\n\n{preview}"
                )

            if action == "snapshot":
                return await self._fresh_snapshot(page, full=bool(arguments.get("full")))

            if action == "wait":
                until = str(arguments.get("until") or "").lower().strip()
                text = arguments.get("text")
                url_pat = arguments.get("url")
                timeout_ms = int(arguments.get("timeout") or 15_000)
                if timeout_ms < 100:
                    timeout_ms = 100
                if timeout_ms > 120_000:
                    timeout_ms = 120_000

                if not until:
                    if normalize_ref(arguments.get("ref")):
                        until = "ref"
                    elif url_pat:
                        until = "url"
                    elif text:
                        until = "text"
                    else:
                        until = "load"

                if until == "timeout":
                    await asyncio.sleep(min(timeout_ms / 1000.0, 30.0))
                    return await self._with_optional_snapshot(
                        page,
                        f"Waited {min(timeout_ms, 30_000)}ms",
                        arguments,
                        default_resnapshot=True,
                    )

                if until == "load":
                    await page.wait_for_load_state("load", timeout=timeout_ms)
                    return await self._with_optional_snapshot(
                        page, "Waited for load", arguments, default_resnapshot=True
                    )

                if until == "networkidle":
                    await page.wait_for_load_state("networkidle", timeout=timeout_ms)
                    return await self._with_optional_snapshot(
                        page,
                        "Waited for networkidle",
                        arguments,
                        default_resnapshot=True,
                    )

                if until == "url":
                    pattern = str(url_pat or text or "").strip()
                    if not pattern:
                        return (
                            "Error: wait until=url needs url= "
                            "(or text=) substring/glob"
                        )
                    await page.wait_for_url(
                        lambda u, p=pattern: p in (u or ""),
                        timeout=timeout_ms,
                    )
                    return await self._with_optional_snapshot(
                        page,
                        f"Waited for URL containing {pattern!r}",
                        arguments,
                        default_resnapshot=True,
                    )

                if until == "text":
                    needle = str(text or "").strip()
                    if not needle:
                        return "Error: wait until=text needs text="
                    await page.get_by_text(needle, exact=False).first.wait_for(
                        state="visible", timeout=timeout_ms
                    )
                    return await self._with_optional_snapshot(
                        page,
                        f"Waited for text {needle!r}",
                        arguments,
                        default_resnapshot=True,
                    )

                if until == "ref":
                    ref = normalize_ref(arguments.get("ref"))
                    if not ref:
                        return "Error: wait until=ref needs ref=@eN"
                    await stamp_interactive(page)
                    loc, label = await resolve_ref_locator(page, ref)
                    if loc is None:
                        deadline = time.time() + (timeout_ms / 1000.0)
                        while time.time() < deadline:
                            await asyncio.sleep(0.25)
                            await stamp_interactive(page)
                            loc, label = await resolve_ref_locator(page, ref)
                            if loc is not None:
                                break
                    if loc is None:
                        return f"Error: {label} after wait"
                    await loc.wait_for(state="visible", timeout=min(timeout_ms, 5_000))
                    return await self._with_optional_snapshot(
                        page,
                        f"Waited for {label}",
                        arguments,
                        default_resnapshot=True,
                    )

                return (
                    "Error: until must be load|networkidle|url|text|ref|timeout"
                )

            if action == "reload":
                hard = bool(arguments.get("hard"))
                if hard:
                    try:
                        cdp = await page.context.new_cdp_session(page)
                        await cdp.send(
                            "Network.setCacheDisabled", {"cacheDisabled": True}
                        )
                        await page.reload(
                            wait_until="domcontentloaded", timeout=45_000
                        )
                        await cdp.send(
                            "Network.setCacheDisabled", {"cacheDisabled": False}
                        )
                    except Exception:  # noqa: BLE001
                        await page.reload(
                            wait_until="domcontentloaded", timeout=45_000
                        )
                else:
                    await page.reload(wait_until="domcontentloaded", timeout=45_000)
                title = await page.title()
                return await self._with_optional_snapshot(
                    page,
                    f"Reloaded{' (hard)' if hard else ''} → {page.url}\n"
                    f"Title: {title}",
                    arguments,
                    default_resnapshot=True,
                )

            if action == "click":
                loc, label = await self._locator_for_target(page, arguments)
                text = arguments.get("text")
                if loc is not None:
                    await loc.click(timeout=15_000)
                    return await self._with_optional_snapshot(
                        page,
                        f"Clicked {label}",
                        arguments,
                        default_resnapshot=True,
                    )
                if label and "not found" in str(label):
                    return f"Error: {label}"
                if text:
                    await page.get_by_text(str(text), exact=False).first.click(
                        timeout=15_000
                    )
                    return await self._with_optional_snapshot(
                        page,
                        f"Clicked text: {text}",
                        arguments,
                        default_resnapshot=True,
                    )
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
                header = f"Typed into {label} ({len(str(text))} chars)"
                if self._want_resnapshot(arguments, default=False):
                    await asyncio.sleep(0.15)
                    snap = await self._fresh_snapshot(page)
                    return f"{header}\n\n{snap}"
                return header

            if action == "select":
                option = str(
                    arguments.get("value") or arguments.get("text") or ""
                ).strip()
                if not option:
                    return "Error: select needs text= (label) or value="
                loc, label = await self._locator_for_target(page, arguments)
                if loc is None:
                    if label and "not found" in str(label):
                        return f"Error: {label}"
                    return "Error: provide ref (@eN) or selector for select"

                selected = False
                detail = ""
                try:
                    tag = await loc.evaluate("el => el.tagName")
                except Exception:  # noqa: BLE001
                    tag = ""
                if str(tag).upper() == "SELECT":
                    try:
                        await loc.select_option(label=option, timeout=8_000)
                        selected = True
                        detail = f"label={option!r}"
                    except Exception:  # noqa: BLE001
                        try:
                            await loc.select_option(value=option, timeout=8_000)
                            selected = True
                            detail = f"value={option!r}"
                        except Exception as exc:  # noqa: BLE001
                            return f"Error: native select failed: {exc}"

                if not selected:
                    await loc.click(timeout=15_000)
                    await asyncio.sleep(0.2)
                    try:
                        await page.get_by_role(
                            "option", name=option, exact=False
                        ).first.click(timeout=8_000)
                        selected = True
                        detail = f"option={option!r}"
                    except Exception:  # noqa: BLE001
                        try:
                            await page.get_by_text(option, exact=False).first.click(
                                timeout=8_000
                            )
                            selected = True
                            detail = f"text={option!r}"
                        except Exception as exc:  # noqa: BLE001
                            return (
                                f"Error: could not select {option!r} "
                                f"on {label}: {exc}"
                            )

                return await self._with_optional_snapshot(
                    page,
                    f"Selected {detail} on {label}",
                    arguments,
                    default_resnapshot=True,
                )

            if action == "hover":
                loc, label = await self._locator_for_target(page, arguments)
                if loc is None:
                    if label and "not found" in str(label):
                        return f"Error: {label}"
                    return "Error: provide ref (@eN) or selector for hover"
                await loc.hover(timeout=15_000)
                return await self._with_optional_snapshot(
                    page,
                    f"Hovered {label}",
                    arguments,
                    default_resnapshot=True,
                )

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
                    texts: list[str] = []
                    total = 0
                    for frame in list(getattr(page, "frames", []) or [page]):
                        try:
                            fl = frame.locator(str(selector))
                            c = await fl.count()
                        except Exception:  # noqa: BLE001
                            continue
                        total += c
                        for i in range(min(c, 30 - len(texts))):
                            t = (await fl.nth(i).inner_text()).strip()
                            if t:
                                texts.append(t)
                        if len(texts) >= 30:
                            break
                    joined = "\n---\n".join(texts) if texts else "(no text)"
                    if len(joined) > 12_000:
                        joined = joined[:12_000] + "\n...[truncated]"
                    return (
                        f"Extracted {len(texts)}/{total} nodes "
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
                if dialog_action not in {
                    "accept",
                    "dismiss",
                    "a",
                    "yes",
                    "ok",
                    "cancel",
                }:
                    return "Error: dialog_action must be accept, dismiss, or list"
                await set_dialog_defaults(
                    page, accept=accept, prompt_text=prompt_text
                )
                return (
                    f"Next JS confirm/prompt will "
                    f"{'ACCEPT' if accept else 'DISMISS'}"
                    + (
                        f" (prompt text set, {len(prompt_text)} chars)"
                        if prompt_text
                        else ""
                    )
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
