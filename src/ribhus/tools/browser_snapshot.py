"""Accessibility / interactive-element snapshots with @eN refs for the browser tool."""

from __future__ import annotations

from typing import Any

# Visible, typically actionable controls. startIndex keeps refs unique across frames.
_INTERACTIVE_JS = """
(startIndex) => {
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
    '[role="listbox"]',
    '[role="menuitem"]',
    '[role="option"]',
    '[role="tab"]',
    '[role="switch"]',
    '[contenteditable="true"]',
  ].join(',');

  document.querySelectorAll('[data-ribhus-ref]').forEach((el) => {
    el.removeAttribute('data-ribhus-ref');
  });

  const seen = new Set();
  const items = [];
  const nodes = Array.from(document.querySelectorAll(SELECTOR));
  const start = Number(startIndex) || 0;
  for (const el of nodes) {
    if (items.length >= 200) break;
    if (seen.has(el)) continue;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    if (el.disabled) continue;

    seen.add(el);
    const ref = 'e' + (start + items.length + 1);
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
    nextIndex: start + items.length,
  };
}
"""

_CLEAR_REFS_JS = """
() => {
  document.querySelectorAll('[data-ribhus-ref]').forEach((el) => {
    el.removeAttribute('data-ribhus-ref');
  });
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
    frames = int(payload.get("frames") or 1)
    lines = [
        f"URL: {url}",
        f"Title: {title}",
        f"Frames: {frames}",
        f"Interactive elements ({len(items)}):",
    ]
    if not items:
        lines.append("  (none tagged — try wait, scroll, or read)")
    for item in items:
        if not isinstance(item, dict):
            continue
        ref = item.get("ref") or "?"
        role = item.get("role") or "element"
        name = item.get("name") or ""
        label = f' "{name}"' if name else ""
        iframe = " (iframe)" if item.get("iframe") else ""
        lines.append(f"  @{ref} [{role}]{iframe}{label}")

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
            "Tip: click/type/select/hover with ref=\"@e1\". "
            "wait until=text|url|networkidle|ref before acting. "
            "Use snapshot full=true for page text."
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
    """Tag interactive nodes (main document + same-origin iframes) with @eN refs."""
    frames = list(getattr(page, "frames", []) or [])
    if not frames:
        frames = [page]

    # Clear refs everywhere first so stale tags don't collide.
    for frame in frames:
        try:
            await frame.evaluate(_CLEAR_REFS_JS)
        except Exception:  # noqa: BLE001
            continue

    all_items: list[dict[str, Any]] = []
    next_index = 0
    main_url = ""
    main_title = ""
    stamped_frames = 0

    for idx, frame in enumerate(frames):
        try:
            raw = await frame.evaluate(_INTERACTIVE_JS, next_index)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(raw, dict):
            continue
        stamped_frames += 1
        if idx == 0:
            main_url = str(raw.get("url") or "")
            main_title = str(raw.get("title") or "")
        items = raw.get("items") if isinstance(raw.get("items"), list) else []
        is_iframe = idx > 0
        for item in items:
            if not isinstance(item, dict):
                continue
            if is_iframe:
                item = {**item, "iframe": True, "frame_index": idx}
            all_items.append(item)
        next_index = int(raw.get("nextIndex") or (next_index + len(items)))

    if not main_url:
        try:
            main_url = str(page.url or "")
            main_title = await page.title()
        except Exception:  # noqa: BLE001
            pass

    return {
        "url": main_url,
        "title": main_title,
        "items": all_items[:200],
        "frames": max(stamped_frames, 1),
    }


async def resolve_ref_locator(page: Any, ref: str) -> tuple[Any | None, str]:
    """Find locator for @eN across main page and iframes."""
    frames = list(getattr(page, "frames", []) or [])
    if not frames:
        frames = [page]
    for frame in frames:
        try:
            loc = frame.locator(f'[data-ribhus-ref="{ref}"]')
            if await loc.count() > 0:
                return loc.first, f"ref=@{ref}"
        except Exception:  # noqa: BLE001
            continue
    return None, f"ref=@{ref} (not found — run snapshot)"


async def resolve_selector_locator(page: Any, selector: str) -> tuple[Any | None, str]:
    """Find CSS selector across main page and iframes (first match wins)."""
    frames = list(getattr(page, "frames", []) or [])
    if not frames:
        frames = [page]
    for frame in frames:
        try:
            loc = frame.locator(selector)
            if await loc.count() > 0:
                return loc.first, f"selector={selector}"
        except Exception:  # noqa: BLE001
            continue
    return None, f"selector={selector} (not found)"


async def install_dialog_hooks(page: Any) -> None:
    frames = list(getattr(page, "frames", []) or [])
    targets = frames or [page]
    for frame in targets:
        try:
            await frame.evaluate(_DIALOG_HOOK_JS)
        except Exception:  # noqa: BLE001
            continue


async def read_js_dialogs(page: Any) -> list[dict[str, Any]]:
    frames = list(getattr(page, "frames", []) or [])
    targets = frames or [page]
    out: list[dict[str, Any]] = []
    for frame in targets:
        try:
            raw = await frame.evaluate(
                "() => Array.isArray(window.__ribhusDialogs) "
                "? window.__ribhusDialogs.splice(0) : []"
            )
        except Exception:  # noqa: BLE001
            continue
        if isinstance(raw, list):
            out.extend(d for d in raw if isinstance(d, dict))
    return out


async def set_dialog_defaults(
    page: Any,
    *,
    accept: bool = True,
    prompt_text: str = "",
) -> None:
    frames = list(getattr(page, "frames", []) or [])
    targets = frames or [page]
    for frame in targets:
        try:
            await frame.evaluate(
                """({ accept, promptText }) => {
                  window.__ribhusNextConfirm = !!accept;
                  window.__ribhusNextPrompt = promptText;
                }""",
                {"accept": accept, "promptText": prompt_text},
            )
        except Exception:  # noqa: BLE001
            continue
