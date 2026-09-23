"""Type and send a WhatsApp message. Call only after explicit approval."""

from __future__ import annotations

import asyncio
from typing import Any

from ribhus.channels.whatsapp_web.selectors import COMPOSE_BOX, SEND_BUTTON, first_visible
from ribhus.channels.whatsapp_web.session import WhatsAppSession

_CONFIRM_SENT = """
(snippet) => {
  const needle = (snippet || '').slice(0, 60);
  const box =
    document.querySelector('#main footer [contenteditable="true"]')
    || document.querySelector('footer [contenteditable="true"]')
    || document.querySelector('#compose')
    || document.querySelector('[contenteditable="true"][data-tab]');
  const composeText = (box && (box.innerText || box.textContent) || '')
    .replace(/\\u200e|\\u200f/g, '')
    .trim();
  if (needle && composeText && composeText.includes(needle.slice(0, 40))) {
    return { ok: false, reason: 'still-in-compose' };
  }

  const log = document.querySelector('#sent-log');
  if (log) {
    const logged = (log.getAttribute('data-text') || '').trim();
    if (needle && logged.includes(needle.slice(0, 40))) {
      return { ok: true, reason: 'sent-log' };
    }
  }

  const main = document.querySelector('#main');
  if (main && needle) {
    const outs = main.querySelectorAll(
      '.message-out, [data-id^="true"], [data-testid="msg-container"]'
    );
    const start = Math.max(0, outs.length - 8);
    for (let i = outs.length - 1; i >= start; i--) {
      const t = (outs[i].innerText || '').replace(/\\u200e|\\u200f/g, '').trim();
      if (t.includes(needle.slice(0, 40))) {
        return { ok: true, reason: 'outgoing-bubble' };
      }
    }
  }

  if (!composeText) {
    return { ok: true, reason: 'compose-cleared' };
  }
  return { ok: false, reason: 'unconfirmed' };
}
"""


async def send_on_page(page: Any, text: str) -> str:
    """Type and send on an already-open page. Returns a short confirmation reason."""
    message = text.strip()
    if not message:
        raise ValueError("Refusing to send an empty WhatsApp message.")

    box = await first_visible(page, COMPOSE_BOX, timeout_ms=8_000)
    if box is None:
        raise RuntimeError(
            "Could not find the WhatsApp compose box. Is a chat open?"
        )

    await box.click()
    await page.keyboard.insert_text(message)

    send_btn = await first_visible(page, SEND_BUTTON, timeout_ms=3_000)
    if send_btn is not None:
        await send_btn.click()
    else:
        await page.keyboard.press("Enter")

    reason = await _confirm_sent(page, message)
    if reason is None:
        raise RuntimeError(
            "Send click ran, but the message was not confirmed "
            "(compose still has text and no matching outgoing bubble). "
            "Check the headed window and retry."
        )
    return reason


async def _confirm_sent(page: Any, message: str) -> str | None:
    snippet = message.strip()
    for _ in range(10):
        try:
            raw = await page.evaluate(_CONFIRM_SENT, snippet)
        except Exception:  # noqa: BLE001
            raw = None
        if isinstance(raw, dict) and raw.get("ok"):
            return str(raw.get("reason") or "ok")
        await asyncio.sleep(0.12)
    return None


class WhatsAppSender:
    def __init__(self, session: WhatsAppSession) -> None:
        self.session = session

    async def send(self, text: str) -> str:
        """Type `text` into the open chat compose box and click Send.

        The caller MUST have already obtained human approval. This method
        does not show a prompt of its own. Returns confirmation reason.
        """
        page = await self.session.ensure_logged_in()
        return await send_on_page(page, text)

    async def clear_compose(self) -> None:
        """Best-effort clear if we typed but did not send."""
        page = self.session.page
        if page is None:
            return
        try:
            box = await first_visible(page, COMPOSE_BOX, timeout_ms=1_500)
            if box is None:
                return
            await box.click()
            await page.keyboard.press("Meta+A")
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
        except Exception:  # noqa: BLE001 — best effort
            return
