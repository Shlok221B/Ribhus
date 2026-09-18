"""Read the open Gmail thread."""

from __future__ import annotations

import asyncio
from typing import Any

from ribhus.channels.gmail_web.session import GmailSession

_EXTRACT = """
() => {
  const main = document.querySelector("div[role='main']");
  if (!main) return { subject: '', messages: [], debug: { noMain: true } };
  const subjectEl = main.querySelector("h2.hP, h2[data-thread-perm-id], h2");
  const subject = (subjectEl && subjectEl.textContent || '').trim();
  const messages = [];
  const blocks = main.querySelectorAll("div.adn, div[data-message-id], div.gs");
  const seen = new Set();
  for (const block of blocks) {
    const emailEl = block.querySelector("[email]");
    const from = emailEl
      ? (emailEl.getAttribute('email') || emailEl.textContent || '').trim()
      : '';
    let body = '';
    const bodyEl =
      block.querySelector("div.a3s") ||
      block.querySelector("div[dir='ltr']") ||
      block.querySelector(".ii.gt");
    if (bodyEl) body = (bodyEl.innerText || '').trim();
    if (!body) continue;
    const key = (from + '|' + body.slice(0, 80)).toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    messages.push({ from, text: body.slice(0, 4000) });
    if (messages.length >= 20) break;
  }
  if (!messages.length) {
    const raw = (main.innerText || '').trim().slice(0, 4000);
    if (raw) messages.push({ from: '', text: raw, meta: 'raw-panel' });
  }
  return { subject, messages, debug: { count: messages.length } };
}
"""


class GmailReader:
    def __init__(self, session: GmailSession) -> None:
        self.session = session

    async def read(self, *, limit: int = 8) -> tuple[str, list[dict[str, Any]]]:
        page = await self.session.ensure_logged_in()
        await asyncio.sleep(0.3)
        try:
            raw = await page.evaluate(_EXTRACT)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Could not read Gmail thread: {exc}") from exc
        subject = str((raw or {}).get("subject") or "")
        messages = (raw or {}).get("messages") or []
        if not isinstance(messages, list):
            messages = []
        cleaned: list[dict[str, Any]] = []
        for m in messages:
            if not isinstance(m, dict):
                continue
            text = str(m.get("text") or "").strip()
            if not text:
                continue
            cleaned.append(
                {
                    "from": str(m.get("from") or ""),
                    "text": text,
                    "meta": m.get("meta"),
                }
            )
        return subject, cleaned[-max(1, min(limit, 20)) :]

    @staticmethod
    def format(subject: str, messages: list[dict[str, Any]]) -> str:
        lines = [f"Subject: {subject or '(unknown)'}"]
        if not messages:
            lines.append("(no message text extracted)")
            return "\n".join(lines)
        lines.append("")
        for i, m in enumerate(messages, 1):
            who = m.get("from") or "unknown"
            lines.append(f"[{i}] from={who}")
            lines.append(str(m.get("text") or ""))
            lines.append("---")
        return "\n".join(lines).rstrip("-").strip()
