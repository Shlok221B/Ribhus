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
# Prefer explicit home phrases; "I'm in X" only when X looks like a place.
_HOME_CITY = re.compile(
    r"(?:i\s+live\s+in|i'?m\s+based\s+in|based\s+in|i\s+am\s+in|"
    r"i'?m\s+in|my\s+(?:city|hometown|home\s*town)\s+is|from)\s+"
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

# Reject garbage captures like "Different Areas That" from "I'm in …".
_PLACE_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "my",
        "our",
        "this",
        "that",
        "these",
        "those",
        "here",
        "there",
        "near",
        "me",
        "you",
        "area",
        "areas",
        "different",
        "various",
        "several",
        "some",
        "any",
        "town",
        "city",
        "place",
        "places",
        "office",
        "home",
        "work",
        "india",
        "world",
        "chat",
        "whatsapp",
        "email",
        "gmail",
        "and",
        "or",
        "but",
        "prefer",
        "with",
        "for",
        "to",
        "in",
    }
)

_KNOWN_PLACES = frozenset(
    {
        "pune",
        "mumbai",
        "delhi",
        "new delhi",
        "bengaluru",
        "bangalore",
        "hyderabad",
        "chennai",
        "kolkata",
        "ahmedabad",
        "jaipur",
        "surat",
        "lucknow",
        "kanpur",
        "nagpur",
        "indore",
        "bhopal",
        "patna",
        "chandigarh",
        "goa",
        "panaji",
        "gurgaon",
        "gurugram",
        "noida",
        "ghaziabad",
        "faridabad",
        "kochi",
        "cochin",
        "trivandrum",
        "thiruvananthapuram",
        "mysore",
        "mysuru",
        "coimbatore",
        "vadodara",
        "rajkot",
        "nashik",
        "aurangabad",
        "baner",
        "hinjewadi",
        "koregaon park",
        "kalyani nagar",
        "viman nagar",
        "kothrud",
        "hadapsar",
        "wakad",
        "indiranagar",
        "koramangala",
        "whitefield",
        "hsr",
        "jayanagar",
        "andheri",
        "bandra",
        "powai",
        "worli",
        "connaught place",
        "saket",
        "dwarka",
    }
)


def is_plausible_place(place: str) -> bool:
    """True if ``place`` looks like a city/area, not a phrase fragment."""
    text = " ".join((place or "").strip().split())
    if len(text) < 3 or len(text) > 48:
        return False
    tokens = [t.casefold().strip(".") for t in text.split() if t.strip(".")]
    if not tokens:
        return False
    if any(t in _PLACE_STOPWORDS for t in tokens):
        return False
    folded = " ".join(tokens)
    if folded in _KNOWN_PLACES:
        return True
    # Unknown but clean single/double token (e.g. neighbourhood names)
    if len(tokens) <= 2 and all(t.isalpha() and len(t) >= 3 for t in tokens):
        return True
    return False


def normalize_place_capture(raw: str) -> str | None:
    """Trim regex capture to a plausible place (stop at 'and' / junk words)."""
    tokens: list[str] = []
    for part in (raw or "").split():
        cleaned = part.strip(".,!?")
        if not cleaned:
            continue
        if cleaned.casefold() in _PLACE_STOPWORDS:
            break
        tokens.append(cleaned)
        folded = " ".join(t.casefold() for t in tokens)
        if folded in _KNOWN_PLACES:
            break
    if not tokens:
        return None
    place = " ".join(part.capitalize() for part in tokens)
    return place if is_plausible_place(place) else None


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
        place = normalize_place_capture(city.group(1))
        if place:
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
