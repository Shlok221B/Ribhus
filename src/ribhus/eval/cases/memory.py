from __future__ import annotations

from ribhus.eval.harness import temp_workspace
from ribhus.eval.models import EvalCase
from ribhus.memory.football import ensure_football_club, get_saved_football_club
from ribhus.memory.service import MemoryService
from ribhus.memory.tools import MemoryRecallTool, MemoryRememberTool


def _service(workspace):
    return MemoryService.from_path(
        workspace / ".ribhus" / "memory.sqlite",
        env_enabled=True,
    )


async def remember_recall() -> None:
    with temp_workspace() as workspace:
        memory = _service(workspace)
        try:
            remember = MemoryRememberTool(memory)
            recall = MemoryRecallTool(memory)
            saved = await remember.execute(
                {"fact": "Prefer Hinglish replies", "key": "language"}
            )
            assert "Saved" in saved
            found = await recall.execute({"query": "Hinglish"})
            assert "Hinglish" in found
        finally:
            memory.close()


def football_club_preference() -> None:
    with temp_workspace() as workspace:
        memory = _service(workspace)
        try:
            club = ensure_football_club(memory, prompt="I support FC Goa")
            assert club and "Goa" in club
            assert get_saved_football_club(memory)
        finally:
            memory.close()


def disable_stops_injection() -> None:
    with temp_workspace() as workspace:
        memory = _service(workspace)
        try:
            memory.remember_fact("Prefer Hinglish replies", key="language")
            injected = memory.prompt_addon("what language")
            assert "Hinglish" in injected
            memory.set_enabled(False)
            assert memory.prompt_addon("what language") == ""
        finally:
            memory.close()


def search_finds_fact() -> None:
    with temp_workspace() as workspace:
        memory = _service(workspace)
        try:
            memory.remember_fact("Home city is Pune", key="home_city")
            hits = memory.search("Pune")
            assert any("Pune" in h.content for h in hits)
        finally:
            memory.close()


CASES = [
    EvalCase("memory-remember-recall", "memory", "memory_remember", "Remember/recall round-trip", remember_recall),
    EvalCase("memory-football-club", "memory", "football_club", "Club preference persists", football_club_preference),
    EvalCase("memory-disable", "memory", "memory.disable", "Disable stops prompt injection", disable_stops_injection),
    EvalCase("memory-search", "memory", "memory.search", "Search finds a saved fact", search_finds_fact),
]
