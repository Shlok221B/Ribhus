"""Read recent messages from the open WhatsApp chat."""

from __future__ import annotations

import asyncio
from typing import Any

from ribhus.channels.whatsapp_web.session import WhatsAppSession


async def read_from_page(page: Any, *, limit: int = 15) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Extract messages from an already-open page (live WhatsApp or HTML fixture)."""
    limit = max(1, min(int(limit), 40))
    await _wait_for_bubbles(page)
    try:
        await page.evaluate(
            """() => {
              const main = document.querySelector('#main');
              if (!main) return;
              const el = main.querySelector('[role="application"]')
                || main.querySelector('.copyable-area')
                || main;
              el.scrollTop = el.scrollHeight;
            }"""
        )
    except Exception:  # noqa: BLE001
        pass
    await asyncio.sleep(0.15)

    debug: dict[str, Any] = {}
    messages: list[dict[str, Any]] = []
    try:
        raw = await page.evaluate(_EXTRACT_MESSAGES)
        messages, debug = parse_extract(raw)
        if not messages:
            await asyncio.sleep(0.4)
            raw = await page.evaluate(_EXTRACT_MESSAGES)
            messages, debug = parse_extract(raw)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Could not read WhatsApp messages: {exc}") from exc

    if not messages:
        fallback = await _raw_panel_text(page)
        if fallback:
            messages = [{"direction": "in", "text": fallback, "meta": "raw-panel"}]
            debug["fallback"] = "raw-panel"
        elif debug:
            debug.setdefault("empty", True)
    return messages[-limit:], debug


async def _wait_for_bubbles(page: Any) -> None:
    selectors = [
        "#main [data-pre-plain-text]",
        "#main span.selectable-text",
        "#main [data-id]",
        "#main .copyable-area",
        "#main",
    ]
    for selector in selectors:
        try:
            await page.wait_for_selector(selector, timeout=4_000, state="attached")
            return
        except Exception:  # noqa: BLE001
            continue


async def _raw_panel_text(page: Any) -> str:
    try:
        blob = (await page.inner_text("#main")).strip()
    except Exception:  # noqa: BLE001
        return ""
    if len(blob) < 8:
        return ""
    if len(blob) > 2500:
        blob = blob[-2500:]
    return blob

# Return {messages, debug}. Try several DOM shapes; never bail after the first.
_EXTRACT_MESSAGES = """
() => {
  const debug = { main: false, pre: 0, dataId: 0, selectable: 0 };
  const main = document.querySelector('#main');
  debug.main = !!main;
  if (!main) return { messages: [], debug };

  const scrollables = [
    main.querySelector('[role="application"]'),
    main.querySelector('.copyable-area'),
    main.querySelector('div[tabindex="-1"]'),
    main
  ].filter(Boolean);
  for (const s of scrollables) {
    try { s.scrollTop = s.scrollHeight; } catch (e) {}
  }

  debug.pre = main.querySelectorAll('[data-pre-plain-text]').length;
  debug.dataId = main.querySelectorAll('[data-id]').length;
  debug.selectable = main.querySelectorAll('span.selectable-text, span.copyable-text').length;

  const header = main.querySelector('header');
  const footer = main.querySelector('footer');
  const skip = (el) =>
    (header && header.contains(el)) || (footer && footer.contains(el));

  const seen = new Set();
  const messages = [];
  const add = (text, outgoing, meta, id) => {
    let t = (text || '').replace(/\\u200e|\\u200f/g, '').trim();
    if (!t || t.length > 4000) return;
    const low = t.toLowerCase();
    if ([
      'type a message', 'search', 'profile details', 'contact info',
      'today', 'yesterday', 'tailored for you'
    ].includes(low)) return;
    const mid = (id || '').trim();
    const key = mid
      ? ('id:' + mid)
      : ((outgoing ? 'out:' : 'in:') + t.slice(0, 240));
    if (seen.has(key)) return;
    seen.add(key);
    messages.push({
      text: t,
      outgoing: !!outgoing,
      meta: meta || '',
      id: mid,
    });
  };

  const outgoingOf = (el, dataId) => {
    const host = el.closest ? (el.closest('[data-id]') || el) : el;
    const id = dataId || host.getAttribute('data-id') || '';
    if (id.startsWith('true')) return true;
    if (id.startsWith('false')) return false;
    return !!(
      host.closest('.message-out') ||
      host.querySelector('[data-icon="msg-dblcheck"], [data-icon="msg-check"], [data-icon="msg-time"]')
    );
  };

  const textOf = (el) => {
    const copy = el.querySelector(
      'span.selectable-text.copyable-text, span.selectable-text, span.copyable-text, .copyable-text span'
    );
    if (copy && copy.innerText) return copy.innerText;
    const dir = el.querySelector('span[dir="ltr"], span[dir="rtl"], span[dir="auto"]');
    if (dir && dir.innerText) return dir.innerText;
    return el.innerText || '';
  };

  for (const el of main.querySelectorAll('[data-pre-plain-text]')) {
    if (skip(el)) continue;
    const host = el.closest ? el.closest('[data-id]') : null;
    const id = host ? (host.getAttribute('data-id') || '') : '';
    add(
      textOf(el),
      outgoingOf(el, id),
      el.getAttribute('data-pre-plain-text') || '',
      id
    );
  }

  for (const el of main.querySelectorAll('[data-id]')) {
    if (skip(el)) continue;
    const id = el.getAttribute('data-id') || '';
    if (!id || id.length < 6) continue;
    add(textOf(el), outgoingOf(el, id), '', id);
  }

  for (const el of main.querySelectorAll('span.selectable-text, span.copyable-text')) {
    if (skip(el)) continue;
    const host = el.closest ? el.closest('[data-id]') : null;
    const id = host ? (host.getAttribute('data-id') || '') : '';
    add(el.innerText, outgoingOf(el, id), '', id);
  }

  return { messages, debug };
}
"""


def parse_extract(raw: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    debug: dict[str, Any] = {}
    items: list[Any]
    if isinstance(raw, dict):
        debug = dict(raw.get("debug") or {})
        items = list(raw.get("messages") or [])
    elif isinstance(raw, list):
        items = raw
    else:
        items = []
    messages: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        messages.append(
            {
                "direction": "out" if item.get("outgoing") else "in",
                "text": text,
                "meta": str(item.get("meta") or "").strip(),
                "id": str(item.get("id") or "").strip(),
            }
        )
    return messages, debug


class WhatsAppReader:
    def __init__(self, session: WhatsAppSession) -> None:
        self.session = session
        self.last_debug: dict[str, Any] = {}

    async def read_messages(self, limit: int = 15) -> list[dict[str, Any]]:
        page = await self.session.ensure_logged_in()
        messages, debug = await read_from_page(page, limit=limit)
        self.last_debug = debug
        return messages

    @staticmethod
    def format(
        messages: list[dict[str, Any]],
        *,
        title: str | None = None,
        debug: dict[str, Any] | None = None,
        include_register: bool = False,
    ) -> str:
        header = f"Chat: {title}\n" if title else ""
        if not messages:
            extra = f" (debug: {debug})" if debug else ""
            return (
                header
                + "No messages could be read in this chat."
                + extra
            )
        if len(messages) == 1 and messages[0].get("meta") == "raw-panel":
            return (
                header
                + "Could not parse individual bubbles; raw conversation panel:\n"
                + messages[0]["text"]
            )
        lines = []
        for msg in messages:
            who = "You" if msg.get("direction") == "out" else "Them"
            meta = f" ({msg['meta']})" if msg.get("meta") else ""
            lines.append(f"{who}{meta}: {msg['text']}")
        body = header + "\n".join(lines)
        if include_register:
            from ribhus.channels.whatsapp_web.register import infer_register

            body += "\n\n" + infer_register(messages)
        return body
