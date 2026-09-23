"""Heuristic preference extraction from user text (no LLM)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ribhus.memory.clubs import FOOTBALL_CLUB_KEY, club_from_text

# Keys we always try to keep visible in the system prompt when set.
PINNED_KEYS: tuple[str, ...] = (
    "language",
    "home_city",
    "budget",
    FOOTBALL_CLUB_KEY,
    "whatsapp_style",
)


@dataclass(frozen=True)
class ExtractedPref:
    key: str
    content: str


_LANGUAGE = re.compile(
    r"(?:prefer|always\s+(?:use|reply\s+in)|reply\s+in|speak(?:\s+in)?)\s+"
    r"(hinglish|hindi|english|devanagari)",
    re.IGNORECASE,
)
_HOME_CITY = re.compile(
    r"(?:i\s+live\s+in|i'?m\s+based\s+in|based\s+in|i'?m\s+in|from)\s+"
    r"([A-Za-z][A-Za-z.\-]*(?:\s+[A-Za-z][A-Za-z.\-]*){0,2})",
    re.IGNORECASE,
)
_BUDGET = re.compile(
    r"(?:budget|cap|max(?:imum)?|under)\s*(?:is|=|:)?\s*₹?\s*([\d,]+(?:\.\d+)?)\s*"
    r"(k|thousand|lakh|lakhs)?",
    re.IGNORECASE,
)
_SUPPORT_CLUB = re.compile(
    r"(?:i\s+support|my\s+(?:favourite|favorite)\s+(?:football\s+)?(?:club|team)\s+is|"
    r"favourite\s+club\s*:)\s+([^\n,.!?]+)",
    re.IGNORECASE,
)


def _normalize_budget(amount: str, unit: str | None) -> str:
    raw = amount.replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return f"Budget: ₹{amount}"
    unit_l = (unit or "").lower()
    if unit_l in {"k", "thousand"}:
        value *= 1000
    elif unit_l in {"lakh", "lakhs"}:
        value *= 100_000
    if value.is_integer():
        return f"Budget preference: ₹{int(value):,}"
    return f"Budget preference: ₹{value:,.2f}"


def extract_prefs_from_text(text: str) -> list[ExtractedPref]:
    """Pull durable prefs from a prompt or answer. Deterministic patterns only."""
    text = text or ""
    found: list[ExtractedPref] = []
    seen_keys: set[str] = set()

    def add(key: str, content: str) -> None:
        if key in seen_keys:
            return
        seen_keys.add(key)
        found.append(ExtractedPref(key=key, content=content))

    lang = _LANGUAGE.search(text)
    if lang:
        name = lang.group(1).capitalize()
        if name.lower() == "hinglish":
            name = "Hinglish"
        add("language", f"Prefer {name} replies")

    city = _HOME_CITY.search(text)
    if city:
        place = " ".join(part.capitalize() for part in city.group(1).split())
        add("home_city", f"Home city: {place}")

    budget = _BUDGET.search(text)
    if budget:
        add("budget", _normalize_budget(budget.group(1), budget.group(2)))

    support = _SUPPORT_CLUB.search(text)
    if support:
        club = club_from_text(support.group(1)) or support.group(1).strip()
        if club:
            add(FOOTBALL_CLUB_KEY, f"Favourite football club: {club}")
    else:
        club = club_from_text(text)
        if club and re.search(
            r"\b(support|favourite|favorite|my\s+(?:football\s+)?(?:club|team))\b",
            text,
            re.IGNORECASE,
        ):
            add(FOOTBALL_CLUB_KEY, f"Favourite football club: {club}")

    return found
