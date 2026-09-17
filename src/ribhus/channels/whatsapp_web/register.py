"""Guess how the contact writes so drafts can match (Hinglish, Hindi, English)."""

from __future__ import annotations

from typing import Any

_HINGLISH = (
    "arre",
    "arey",
    "theeke",
    "theek",
    "yaar",
    "bhai",
    "kya",
    "hai",
    "nahi",
    "nahin",
    "haan",
    "acha",
    "accha",
    "mat",
    "kar",
    "rha",
    "raha",
    "gaya",
    "kahan",
    "kab",
    "abhi",
    "kal",
    "bas",
    "namaste",
    "ok bro",
    "scene",
    "pakka",
    "bilkul",
    "thoda",
    "zyada",
)


def infer_register(messages: list[dict[str, Any]]) -> str:
    """Return a one-line hint for the model when drafting a WhatsApp reply."""
    incoming = [
        str(m.get("text") or "")
        for m in messages
        if m.get("direction") != "out" and m.get("meta") != "raw-panel"
    ]
    sample = " ".join(incoming[-8:] or [str(m.get("text") or "") for m in messages[-8:]])
    if not sample.strip():
        return "Match the contact's language and tone from context."

    compact = sample.casefold()
    has_devanagari = any("\u0900" <= ch <= "\u097f" for ch in sample)
    hinglish = any(marker in compact for marker in _HINGLISH)

    if hinglish and not has_devanagari:
        return (
            "Draft register: casual Hinglish in Roman script "
            "(like 'arre theeke'). Do not switch to formal Hindi or stiff English."
        )
    if has_devanagari:
        return (
            "Draft register: Hindi in Devanagari. Stay natural — "
            "not overly formal unless they are."
        )
    return "Draft register: match their English tone and length from the last messages."
