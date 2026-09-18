"""Known football clubs and key name (no MemoryService imports)."""

from __future__ import annotations

import re

FOOTBALL_CLUB_KEY = "football_club"

# Longest names first so "Manchester City" wins over "City".
KNOWN_CLUBS = (
    "Manchester City",
    "Manchester United",
    "Mumbai City",
    "Bengaluru FC",
    "Kerala Blasters",
    "ATK Mohun Bagan",
    "Mohun Bagan",
    "East Bengal",
    "Chennaiyin",
    "Goa FC",
    "FC Goa",
    "Jamshedpur",
    "Hyderabad FC",
    "Odisha FC",
    "NorthEast United",
    "Real Madrid",
    "Bayern Munich",
    "Borussia Dortmund",
    "Paris Saint-Germain",
    "Inter Milan",
    "AC Milan",
    "Atletico Madrid",
    "Atlético Madrid",
    "Tottenham",
    "Newcastle",
    "Aston Villa",
    "West Ham",
    "Nottingham Forest",
    "Crystal Palace",
    "Brighton",
    "Liverpool",
    "Chelsea",
    "Arsenal",
    "Barcelona",
    "Juventus",
    "Napoli",
    "PSG",
)

_CLUB_IN_PROMPT = re.compile(
    r"\b("
    + "|".join(re.escape(c) for c in sorted(KNOWN_CLUBS, key=len, reverse=True))
    + r")\b",
    re.IGNORECASE,
)


def club_from_text(text: str) -> str | None:
    match = _CLUB_IN_PROMPT.search(text or "")
    if not match:
        return None
    found = match.group(1)
    for club in KNOWN_CLUBS:
        if club.lower() == found.lower():
            return club
    return found
