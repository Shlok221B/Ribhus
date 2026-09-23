"""Accessibility / interactive-element snapshots with @eN refs for the browser tool."""

from __future__ import annotations

from typing import Any

# Visible, typically actionable controls.
_INTERACTIVE_JS = """
() => {
  const SELECTOR = [
    'a[href]',
    'button',
    'input:not([type="hidden"])',
    'select',
    'textarea',
    '[role="button"]',
    '[role="link"]',
    '[role="textbox"]',
    '[role="searchbox"]',
    '[role="checkbox"]',
    '[role="radio"]',
    '[role="combobox"]',
    '[role="menuitem"]',
    '[role="tab"]',
    '[role="switch"]',
    '[role="option"]',
    '[contenteditable="true"]',
  ].join(',');

  document.querySelectorAll('[data-ribhus-ref]').forEach((el) => {
    el.removeAttribute('data-ribhus-ref');
  });

  const seen = new Set();
  const items = [];
  const nodes = Array.from(document.querySelectorAll(SELECTOR));
  for (const el of nodes) {
    if (items.length >= 200) break;
    if (seen.has(el)) continue;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    if (el.disabled) continue;

    seen.add(el);
    const ref = 'e' + (items.length + 1);
    el.setAttribute('data-ribhus-ref', ref);
    const role =
      el.getAttribute('role')
      || (el.tagName === 'A' ? 'link'
        : el.tagName === 'BUTTON' ? 'button'
        : el.tagName === 'SELECT' ? 'combobox'
        : el.tagName === 'TEXTAREA' ? 'textbox'
        : el.tagName === 'INPUT' ? (el.type === 'checkbox' ? 'checkbox'
          : el.type === 'radio' ? 'radio'
          : el.type === 'submit' || el.type === 'button' ? 'button'
          : 'textbox')
        : el.tagName.toLowerCase());
    let name = (
      el.getAttribute('aria-label')
      || el.getAttribute('title')
      || el.getAttribute('placeholder')
      || (el.labels && el.labels[0] && el.labels[0].innerText)
      || el.innerText
      || el.value
      || ''
    );
    name = String(name).replace(/\\s+/g, ' ').trim().slice(0, 80);
    items.push({
      ref,
      role,
      name,
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type') || '',
    });
  }
  return {
    url: location.href,
    title: document.title || '',
    items,
  };
}
"""

_DIALOG_HOOK_JS = """
() => {
  if (window.__ribhusDialogHooked) return 'already';
  window.__ribhusDialogHooked = true;
  window.__ribhusDialogs = [];
  window.__ribhusNextConfirm = true;
  window.__ribhusNextPrompt = '';
  window.alert = (m) => {
    window.__ribhusDialogs.push({ type: 'alert', message: String(m) });
  };
  window.confirm = (m) => {
    window.__ribhusDialogs.push({ type: 'confirm', message: String(m) });
    return !!window.__ribhusNextConfirm;
  };
  window.prompt = (m, d) => {
    window.__ribhusDialogs.push({ type: 'prompt', message: String(m), default: d });
    return window.__ribhusNextPrompt !== null && window.__ribhusNextPrompt !== undefined
      ? window.__ribhusNextPrompt
      : (d == null ? '' : String(d));
  };
  return 'ok';
}
"""


def format_snapshot(payload: dict[str, Any], *, full: bool = False) -> str:
    """Render interactive refs (+ optional body text) for the model."""
    url = str(payload.get("url") or "")
    title = str(payload.get("title") or "")
    items = payload.get("items") or []
    lines = [
        f"URL: {url}",
        f"Title: {title}",
        f"Interactive elements ({len(items)}):",
    ]
    if not items:
        lines.append("  (none tagged — try read/extract or scroll)")
    for item in items:
        if not isinstance(item, dict):
            continue
        ref = item.get("ref") or "?"
        role = item.get("role") or "element"
        name = item.get("name") or ""
        label = f' "{name}"' if name else ""
        lines.append(f"  @{ref} [{role}]{label}")

    body = str(payload.get("body") or "").strip()
    if full and body:
        if len(body) > 8_000:
            body = body[:8_000] + "\n...[truncated]"
        lines.append("")
        lines.append("Page text:")
        lines.append(body)
    else:
        lines.append("")
        lines.append(
            "Tip: click/type with ref=\"@e1\" (or ref=\"e1\"). "
            "Use snapshot full=true for page text, or action=read."
        )
    return "\n".join(lines)


def normalize_ref(value: object) -> str | None:
    """Accept '@e3', 'e3', or '3' → 'e3'."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("@"):
        text = text[1:]
    if text.isdigit():
        text = f"e{text}"
    if not text.startswith("e") or not text[1:].isdigit():
        return None
    return text


async def stamp_interactive(page: Any) -> dict[str, Any]:
    """Tag interactive nodes with data-ribhus-ref and return metadata."""
    raw = await page.evaluate(_INTERACTIVE_JS)
    if not isinstance(raw, dict):
        return {"url": "", "title": "", "items": []}
    items = raw.get("items") if isinstance(raw.get("items"), list) else []
    return {
        "url": str(raw.get("url") or ""),
        "title": str(raw.get("title") or ""),
        "items": items,
    }


async def install_dialog_hooks(page: Any) -> None:
    try:
        await page.evaluate(_DIALOG_HOOK_JS)
    except Exception:  # noqa: BLE001
        return


async def read_js_dialogs(page: Any) -> list[dict[str, Any]]:
    try:
        raw = await page.evaluate(
            "() => Array.isArray(window.__ribhusDialogs) "
            "? window.__ribhusDialogs.splice(0) : []"
        )
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(raw, list):
        return []
    return [d for d in raw if isinstance(d, dict)]


async def set_dialog_defaults(
    page: Any,
    *,
    accept: bool = True,
    prompt_text: str = "",
) -> None:
    try:
        await page.evaluate(
            """({ accept, promptText }) => {
              window.__ribhusNextConfirm = !!accept;
              window.__ribhusNextPrompt = promptText;
            }""",
            {"accept": accept, "promptText": prompt_text},
        )
    except Exception:  # noqa: BLE001
        return
