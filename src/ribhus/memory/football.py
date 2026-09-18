"""Resolve the user's football club from semantic memory or recent episodes."""

from __future__ import annotations

from ribhus.memory.clubs import FOOTBALL_CLUB_KEY, club_from_text
from ribhus.memory.service import MemoryService

__all__ = [
    "FOOTBALL_CLUB_KEY",
    "club_from_text",
    "ensure_football_club",
    "get_saved_football_club",
    "infer_football_club_from_episodes",
]


def get_saved_football_club(memory: MemoryService) -> str | None:
    record = memory.store.get_by_key("semantic", FOOTBALL_CLUB_KEY)
    if record is None or record.disabled:
        return None
    named = club_from_text(record.content)
    return named or record.content.strip() or None


def infer_football_club_from_episodes(memory: MemoryService) -> str | None:
    """Pick the most-mentioned known club in recent episodic memory."""
    counts: dict[str, int] = {}
    for episode in memory.list(kind="episodic", limit=40):
        club = club_from_text(episode.content)
        if club:
            counts[club] = counts.get(club, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda item: item[1])[0]


def ensure_football_club(
    memory: MemoryService,
    *,
    prompt: str = "",
) -> str | None:
    """Return the club to follow, persisting semantic memory when inferred.

    Order: named in this prompt → saved semantic → frequent in episodes.
    """
    if not memory.enabled:
        return club_from_text(prompt) or None

    from_prompt = club_from_text(prompt)
    if from_prompt:
        memory.remember_fact(
            f"Favourite football club: {from_prompt}",
            key=FOOTBALL_CLUB_KEY,
        )
        return from_prompt

    saved = get_saved_football_club(memory)
    if saved:
        return saved

    inferred = infer_football_club_from_episodes(memory)
    if inferred:
        memory.remember_fact(
            f"Favourite football club: {inferred}",
            key=FOOTBALL_CLUB_KEY,
        )
        return inferred
    return None
