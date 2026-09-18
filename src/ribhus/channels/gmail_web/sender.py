"""Compose and send on Gmail Web. Call only after explicit approval.

New messages prefer Gmail's compose deep-link (`?tf=cm&to=&su=&body=`), which
pre-fills recipients and avoids the flaky People Kit "To" chip input.
UI compose is the fallback.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlencode

from ribhus.channels.gmail_web.selectors import (
    BODY_FIELD,
    COMPOSE_BUTTON,
    COMPOSE_DIALOG,
    REPLY_BUTTON,
    SEND_BUTTON,
    SUBJECT_FIELD,
    TO_FIELD,
    first_visible,
)
from ribhus.channels.gmail_web.session import GmailSession

_COMPOSE_URL = "https://mail.google.com/mail/u/0/"


def _norm_email(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip().lower())


class GmailSender:
    def __init__(self, session: GmailSession) -> None:
        self.session = session

    async def send_new(self, *, to: str, subject: str, body: str) -> None:
        to = to.strip()
        subject = subject.strip()
        body = body.strip()
        if not to or "@" not in to:
            raise ValueError("Recipient must be an email address")
        if not subject:
            raise ValueError("Subject is required")
        if not body:
            raise ValueError("Body is required")

        page = await self.session.ensure_logged_in()
        await self._dismiss_open_compose(page)

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                await self._send_new_via_url(page, to=to, subject=subject, body=body)
                await self._after_send_cleanup(page)
                return
            except Exception as url_exc:  # noqa: BLE001
                last_error = url_exc
                await self._dismiss_open_compose(page)
                try:
                    await self._send_new_via_ui(page, to=to, subject=subject, body=body)
                    await self._after_send_cleanup(page)
                    return
                except Exception as ui_exc:  # noqa: BLE001
                    last_error = ui_exc
                    await self._dismiss_open_compose(page)
                    if attempt == 0:
                        await asyncio.sleep(0.6)
                        continue
                    raise RuntimeError(
                        f"Gmail send failed after retry. "
                        f"URL compose: {url_exc}; UI compose: {ui_exc}"
                    ) from ui_exc
        if last_error is not None:
            raise last_error

    async def send_reply(self, body: str) -> None:
        body = body.strip()
        if not body:
            raise ValueError("Body is required")

        page = await self.session.ensure_logged_in()
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                reply = await first_visible(page, REPLY_BUTTON, timeout_ms=8_000)
                if reply is None:
                    raise RuntimeError(
                        "Could not find Reply. Open a thread with email_open / email_reply first."
                    )
                await reply.click()
                await asyncio.sleep(0.6)

                dialog = await self._compose_root(page)
                await self._fill_body(page, dialog, body)
                await self._click_send(page, dialog)
                await self._wait_compose_closed(page, dialog)
                await self._after_send_cleanup(page)
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                await self._dismiss_open_compose(page)
                if attempt == 0:
                    await asyncio.sleep(0.5)
                    continue
                raise RuntimeError(f"Gmail reply failed after retry: {exc}") from exc
        if last_error is not None:
            raise last_error

    async def _send_new_via_url(
        self,
        page: Any,
        *,
        to: str,
        subject: str,
        body: str,
    ) -> None:
        query = urlencode(
            {
                "fs": "1",
                "tf": "cm",
                "to": to,
                "su": subject,
                "body": body,
            }
        )
        await page.goto(
            f"{_COMPOSE_URL}?{query}",
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        await asyncio.sleep(2.0)

        # Deep-link already set To — wait for Send (or subject/body) to prove compose opened.
        send = await first_visible(page, SEND_BUTTON, timeout_ms=15_000)
        subject_box = await first_visible(page, SUBJECT_FIELD, timeout_ms=3_000)
        body_box = await first_visible(page, BODY_FIELD, timeout_ms=3_000)
        if send is None and subject_box is None and body_box is None:
            raise RuntimeError("Compose window did not open from deep-link")

        dialog = await self._compose_root(page)
        scope = dialog or page

        # Only touch To if the pre-filled recipient is missing.
        if not await self._to_looks_set(scope, to):
            try:
                await self._fill_to(page, dialog, to)
            except Exception as exc:  # noqa: BLE001
                # Recipient may still be present as a chip the text scan missed.
                if not await self._to_looks_set(scope, to):
                    raise RuntimeError(
                        f"Deep-link opened compose but To looks empty ({exc})"
                    ) from exc

        await self._ensure_subject(page, dialog, subject)
        await self._ensure_body(page, dialog, body)
        await self._click_send(page, dialog)
        await self._wait_compose_closed(page, dialog)

    async def _send_new_via_ui(
        self,
        page: Any,
        *,
        to: str,
        subject: str,
        body: str,
    ) -> None:
        # Inbox keyboard shortcut "c" often opens compose more reliably than the button.
        try:
            await page.keyboard.press("c")
            await asyncio.sleep(0.8)
        except Exception:  # noqa: BLE001
            pass

        dialog = await self._compose_root(page)
        if dialog is None:
            compose = await first_visible(page, COMPOSE_BUTTON, timeout_ms=8_000)
            if compose is None:
                raise RuntimeError("Could not find Gmail Compose button")
            await compose.click()
            await asyncio.sleep(0.9)
            dialog = await self._compose_root(page)

        await self._fill_to(page, dialog, to)
        await self._ensure_subject(page, dialog, subject)
        await self._ensure_body(page, dialog, body)
        await self._click_send(page, dialog)
        await self._wait_compose_closed(page, dialog)

    async def _dismiss_open_compose(self, page: Any) -> None:
        """Close leftover compose drafts so a fresh window can open."""
        for _ in range(3):
            dialog = await first_visible(page, COMPOSE_DIALOG, timeout_ms=600)
            if dialog is None:
                return
            try:
                await page.keyboard.press("Escape")
            except Exception:  # noqa: BLE001
                return
            await asyncio.sleep(0.35)
            # Gmail may ask to discard — confirm if a dialog button appears.
            for label in ("Discard", "OK", "Yes"):
                try:
                    btn = page.get_by_role("button", name=label).first
                    if await btn.is_visible(timeout=400):
                        await btn.click(timeout=1_000)
                        await asyncio.sleep(0.3)
                        break
                except Exception:  # noqa: BLE001
                    continue

    async def _compose_root(self, page: Any) -> Any | None:
        return await first_visible(page, COMPOSE_DIALOG, timeout_ms=8_000)

    async def _find_in(self, root: Any | None, selectors: list[str], *, timeout_ms: int):
        if root is None:
            return None
        for selector in selectors:
            try:
                loc = root.locator(selector).first
                await loc.wait_for(state="visible", timeout=timeout_ms)
                return loc
            except Exception:  # noqa: BLE001
                continue
        return None

    async def _fill_to(self, page: Any, root: Any | None, to: str) -> None:
        scope = root or page
        for label in ("Recipients", "To"):
            try:
                chip = scope.get_by_text(label, exact=True).first
                if await chip.is_visible(timeout=800):
                    await chip.click(timeout=1_000)
                    await asyncio.sleep(0.25)
                    break
            except Exception:  # noqa: BLE001
                pass

        to_box = await self._find_in(root, TO_FIELD, timeout_ms=5_000)
        if to_box is None:
            to_box = await first_visible(page, TO_FIELD, timeout_ms=5_000)
        if to_box is None:
            # Last resort: focus compose and type "to:" via keyboard navigation.
            await page.keyboard.press("Tab")
            await page.keyboard.type(to, delay=20)
            await page.keyboard.press("Enter")
            await asyncio.sleep(0.3)
            if await self._to_looks_set(scope, to):
                return
            raise RuntimeError(
                "Could not find Gmail To field. Close leftover compose drafts "
                "in the Chromium window and retry."
            )

        await to_box.click(timeout=3_000)
        await asyncio.sleep(0.15)
        for combo in ("Meta+a", "Control+a"):
            try:
                await page.keyboard.press(combo)
            except Exception:  # noqa: BLE001
                pass
        await page.keyboard.press("Backspace")
        await page.keyboard.type(to, delay=20)
        await asyncio.sleep(0.45)
        await page.keyboard.press("Enter")
        await asyncio.sleep(0.25)
        await page.keyboard.press("Tab")
        await asyncio.sleep(0.25)

        if not await self._to_looks_set(scope, to):
            raise RuntimeError(
                f"Gmail did not accept the To address {to!r}."
            )

    async def _to_looks_set(self, root: Any, to: str) -> bool:
        target = _norm_email(to)
        local = target.split("@", 1)[0]
        try:
            for selector in TO_FIELD:
                try:
                    loc = root.locator(selector).first
                    if await loc.count() == 0:
                        continue
                    try:
                        value = _norm_email(await loc.input_value(timeout=400))
                    except Exception:  # noqa: BLE001
                        value = ""
                    try:
                        text_bits = _norm_email(await loc.inner_text(timeout=400))
                    except Exception:  # noqa: BLE001
                        text_bits = ""
                    blob = value + text_bits
                    if target in blob or (local and local in blob):
                        return True
                except Exception:  # noqa: BLE001
                    continue
            text = _norm_email(await root.inner_text(timeout=2_000))
        except Exception:  # noqa: BLE001
            return False
        if target in text:
            return True
        return bool(local) and local in text

    async def _ensure_subject(self, page: Any, root: Any | None, subject: str) -> None:
        sub = await self._find_in(root, SUBJECT_FIELD, timeout_ms=4_000)
        if sub is None:
            sub = await first_visible(page, SUBJECT_FIELD, timeout_ms=3_000)
        if sub is None:
            return
        try:
            current = (await sub.input_value(timeout=1_000)).strip()
        except Exception:  # noqa: BLE001
            current = ""
        if current == subject:
            return
        await sub.click(timeout=2_000)
        try:
            await sub.fill(subject)
        except Exception:  # noqa: BLE001
            await page.keyboard.press("Meta+a")
            await page.keyboard.press("Control+a")
            await page.keyboard.type(subject, delay=12)

    async def _ensure_body(self, page: Any, root: Any | None, body: str) -> None:
        box = await self._find_in(root, BODY_FIELD, timeout_ms=5_000)
        if box is None:
            box = await first_visible(page, BODY_FIELD, timeout_ms=4_000)
        if box is None:
            raise RuntimeError("Could not find Gmail message body")
        try:
            current = (await box.inner_text(timeout=1_500)).strip()
        except Exception:  # noqa: BLE001
            current = ""
        # Deep-link may truncate long bodies — refill when missing/short.
        if current and body[:40] in current:
            return
        await self._fill_body(page, root, body)

    async def _fill_body(self, page: Any, root: Any | None, body: str) -> None:
        box = await self._find_in(root, BODY_FIELD, timeout_ms=5_000)
        if box is None:
            box = await first_visible(page, BODY_FIELD, timeout_ms=4_000)
        if box is None:
            raise RuntimeError("Could not find Gmail message body")
        await box.click(timeout=3_000)
        await asyncio.sleep(0.1)
        try:
            await box.fill(body)
        except Exception:  # noqa: BLE001
            await page.keyboard.press("Meta+a")
            await page.keyboard.press("Control+a")
            await page.keyboard.press("Backspace")
            await page.keyboard.insert_text(body)
        await asyncio.sleep(0.2)

    async def _click_send(self, page: Any, root: Any | None) -> None:
        """Focus compose body, then Send via button click and Cmd/Ctrl+Enter."""
        body = await self._find_in(root, BODY_FIELD, timeout_ms=2_000)
        if body is None:
            body = await first_visible(page, BODY_FIELD, timeout_ms=2_000)
        if body is not None:
            try:
                await body.click(timeout=2_000)
                await asyncio.sleep(0.15)
            except Exception:  # noqa: BLE001
                pass

        clicked = await self._click_send_button(page, root)
        if not clicked:
            await page.keyboard.press("Control+Enter")
            await asyncio.sleep(0.2)
            await page.keyboard.press("Meta+Enter")
            await asyncio.sleep(0.35)

        # JS fallback if compose is still open.
        if await first_visible(page, COMPOSE_DIALOG, timeout_ms=500) is not None:
            await page.evaluate(
                """() => {
                  const nodes = Array.from(
                    document.querySelectorAll('[role="button"], button, div.T-I')
                  );
                  const send = nodes.find((el) => {
                    const label = (
                      el.getAttribute('aria-label') ||
                      el.getAttribute('data-tooltip') ||
                      el.textContent ||
                      ''
                    ).trim();
                    if (!/^Send\\b/i.test(label)) return false;
                    if (/feedback|invite|money|schedule/i.test(label)) return false;
                    const r = el.getBoundingClientRect();
                    return r.width > 10 && r.height > 10;
                  });
                  if (send) send.click();
                }"""
            )
            await asyncio.sleep(0.4)

    async def _click_send_button(self, page: Any, root: Any | None) -> bool:
        candidates: list[Any] = []
        for scope in (root, page):
            if scope is None:
                continue
            try:
                candidates.append(
                    scope.get_by_role(
                        "button", name=re.compile(r"^Send\b", re.IGNORECASE)
                    ).first
                )
            except Exception:  # noqa: BLE001
                pass
            try:
                candidates.append(
                    scope.locator(
                        "div[role='button']", has_text=re.compile(r"^Send$")
                    ).first
                )
            except Exception:  # noqa: BLE001
                pass

        found = await self._find_in(root, SEND_BUTTON, timeout_ms=2_500)
        if found is not None:
            candidates.append(found)
        found = await first_visible(page, SEND_BUTTON, timeout_ms=2_500)
        if found is not None:
            candidates.append(found)

        for loc in candidates:
            try:
                if not await loc.is_visible(timeout=800):
                    continue
                await loc.scroll_into_view_if_needed(timeout=1_000)
                await loc.click(timeout=2_000, force=True)
                await asyncio.sleep(0.35)
                return True
            except Exception:  # noqa: BLE001
                continue
        return False

    async def _message_sent(self, page: Any) -> bool:
        try:
            toast = page.get_by_text(re.compile(r"Message sent", re.I)).first
            if await toast.is_visible(timeout=500):
                return True
        except Exception:  # noqa: BLE001
            pass
        try:
            # Gmail sometimes shows "View message" link after send.
            link = page.get_by_text(re.compile(r"^View message$", re.I)).first
            if await link.is_visible(timeout=400):
                return True
        except Exception:  # noqa: BLE001
            pass
        return False

    async def _after_send_cleanup(self, page: Any) -> None:
        """Leave Gmail on inbox so the next action starts clean."""
        try:
            await self.session.go_inbox()
        except Exception:  # noqa: BLE001
            try:
                await self._dismiss_open_compose(page)
            except Exception:  # noqa: BLE001
                pass

    async def _wait_compose_closed(self, page: Any, dialog: Any | None) -> None:
        for _ in range(8):
            await asyncio.sleep(0.4)
            if await self._message_sent(page):
                return
            still = await first_visible(page, COMPOSE_DIALOG, timeout_ms=400)
            if still is None:
                # Compose gone without toast is still usually a successful send.
                return

        # One more focused send attempt.
        body = await first_visible(page, BODY_FIELD, timeout_ms=800)
        if body is not None:
            try:
                await body.click(timeout=1_000)
            except Exception:  # noqa: BLE001
                pass
        await page.keyboard.press("Control+Enter")
        await page.keyboard.press("Meta+Enter")
        await self._click_send_button(page, dialog)
        await asyncio.sleep(1.0)

        if await self._message_sent(page):
            return
        still = await first_visible(page, COMPOSE_DIALOG, timeout_ms=700)
        if still is not None:
            raise RuntimeError(
                "Compose is still open — draft was filled but Send did not fire. "
                "Retry the send."
            )
