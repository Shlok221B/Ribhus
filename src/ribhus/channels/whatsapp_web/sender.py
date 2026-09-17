"""Type and send a WhatsApp message. Call only after explicit approval."""

from __future__ import annotations

import asyncio
from typing import Any

from ribhus.channels.whatsapp_web.selectors import COMPOSE_BOX, SEND_BUTTON, first_visible
from ribhus.channels.whatsapp_web.session import WhatsAppSession


async def send_on_page(page: Any, text: str) -> None:
    """Type and send on an already-open page (live WhatsApp or HTML fixture)."""
    message = text.strip()
    if not message:
        raise ValueError("Refusing to send an empty WhatsApp message.")

    box = await first_visible(page, COMPOSE_BOX, timeout_ms=8_000)
    if box is None:
        raise RuntimeError(
            "Could not find the WhatsApp compose box. Is a chat open?"
        )

    await box.click()
    await asyncio.sleep(0.15)
    await page.keyboard.insert_text(message)
    await asyncio.sleep(0.2)

    send_btn = await first_visible(page, SEND_BUTTON, timeout_ms=3_000)
    if send_btn is not None:
        await send_btn.click()
    else:
        await page.keyboard.press("Enter")
    await asyncio.sleep(0.25)


class WhatsAppSender:
    def __init__(self, session: WhatsAppSession) -> None:
        self.session = session

    async def send(self, text: str) -> None:
        """Type `text` into the open chat compose box and click Send.

        The caller MUST have already obtained human approval. This method
        does not show a prompt of its own.
        """
        page = await self.session.ensure_logged_in()
        await send_on_page(page, text)

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
