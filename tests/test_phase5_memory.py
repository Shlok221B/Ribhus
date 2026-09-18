from __future__ import annotations

import json
from pathlib import Path

import pytest

from ribhus.agent.loop import Agent
from ribhus.memory.service import MemoryService
from ribhus.memory.tools import MemoryRecallTool, MemoryRememberTool
from ribhus.models.base import ModelResponse
from ribhus.skills.installer import create_skill, install_skill, install_skill_with_warnings
from ribhus.skills.loader import load_skill
from ribhus.skills.package import SkillPackageError, validate_skill
from ribhus.skills.registry import SkillRegistry
from ribhus.tools.registry import default_registry


def _memory(tmp_path: Path, *, enabled: bool = True) -> MemoryService:
    return MemoryService.from_path(tmp_path / "memory.sqlite", env_enabled=enabled)


def test_semantic_survives_reopen(tmp_path: Path):
    first = _memory(tmp_path)
    saved = first.remember_fact("Prefer Hinglish replies", key="language")
    first.close()
    second = _memory(tmp_path)
    got = second.get(saved.id)
    assert got.content == "Prefer Hinglish replies"
    assert got.kind == "semantic"
    assert "Hinglish" in second.prompt_addon()


def test_edit_delete_disable_export(tmp_path: Path):
    memory = _memory(tmp_path)
    record = memory.remember_fact("Budget cap is 8000")
    memory.edit(record.id, "Budget cap is ₹8,000")
    assert "₹8,000" in memory.get(record.id).content
    memory.disable(record.id)
    assert memory.get(record.id).disabled
    assert "8000" not in memory.prompt_addon()
    memory.enable(record.id)
    exported = memory.export()
    assert exported["enabled"] is True
    assert any(item["id"] == record.id for item in exported["memories"])
    memory.delete(record.id)
    with pytest.raises(FileNotFoundError):
        memory.get(record.id)


def test_global_disable_skips_prompt_and_writes(tmp_path: Path):
    memory = _memory(tmp_path)
    memory.remember_fact("I live in Pune")
    memory.set_enabled(False)
    assert memory.enabled is False
    assert memory.prompt_addon() == ""
    assert memory.record_episode("task", "done") is None
    assert memory.search("Pune") == []


def test_env_disable(tmp_path: Path):
    memory = _memory(tmp_path, enabled=False)
    memory.remember_fact("stored anyway via CLI")
    assert memory.prompt_addon() == ""


@pytest.mark.asyncio
async def test_memory_tools(tmp_path: Path):
    memory = _memory(tmp_path)
    remember = MemoryRememberTool(memory)
    recall = MemoryRecallTool(memory)
    saved = await remember.execute({"fact": "Vegetarian meals", "key": "diet"})
    assert "sem_" in saved or "Saved" in saved
    hits = await recall.execute({"query": "Vegetarian"})
    assert "Vegetarian meals" in hits


@pytest.mark.asyncio
async def test_agent_records_episode(tmp_path: Path):
    from ribhus.tools.registry import ToolRegistry

    memory = _memory(tmp_path)

    class FakeModel:
        async def generate(self, messages, tools=None):
            return ModelResponse(text="Namaste, done.", tool_calls=[], raw=None)

    agent = Agent(
        model=FakeModel(),  # type: ignore[arg-type]
        tools=ToolRegistry(),
        max_iterations=3,
        memory=memory,
        skill_names=["travel"],
    )
    state = await agent.run("Find a hotel in Goa")
    assert state.finished
    episodes = memory.list(kind="episodic")
    assert len(episodes) == 1
    assert "Goa" in episodes[0].content
    assert "travel" in episodes[0].content
    short = memory.list(kind="short_term")
    assert short
    addon = memory.prompt_addon()
    assert "Last turn" in addon or "Goa" in addon


def test_default_registry_memory_tools(tmp_path: Path):
    memory = _memory(tmp_path)
    names = default_registry(tmp_path, memory=memory).names()
    assert "memory_remember" in names
    assert "memory_recall" in names
    assert "memory_remember" not in default_registry(tmp_path).names()


def test_travel_skill_package_and_triggers():
    bundled = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "ribhus"
        / "skills"
        / "bundled"
        / "travel"
    )
    warnings = validate_skill(bundled)
    assert warnings == []
    skill = load_skill(bundled)
    assert skill.name == "travel"
    assert skill.matches("Find me a hotel in Goa under ₹8,000 for Friday and Saturday.")
    assert skill.matches("trip to Jaipur")
    assert not skill.matches("what is the weather in Goa")
    assert "do not book" in skill.instructions.lower() or "Does not book" in (
        bundled / "README.md"
    ).read_text(encoding="utf-8")


def test_install_travel_into_workspace(tmp_path: Path):
    skill, warnings = install_skill_with_warnings("travel", workspace=tmp_path)
    assert skill.name == "travel"
    assert (tmp_path / ".ribhus" / "skills" / "travel" / "README.md").exists()
    assert (tmp_path / ".ribhus" / "skills" / "travel" / "tools.py").exists()
    registry = SkillRegistry.load_default(tmp_path)
    assert "travel" in registry.names()
    _ = warnings


def test_create_skill_full_package(tmp_path: Path):
    path = create_skill("pack-me", workspace=tmp_path, description="Demo pack")
    validate_skill(path)
    for name in ("config.yaml", "skill.md", "README.md", "tools.py", "examples.md"):
        assert (path / name).exists()
    assert (path / "tests" / "test_skill.py").exists()
    installed = install_skill(path, workspace=tmp_path)
    assert installed.name == "pack-me"


def test_validate_rejects_incomplete(tmp_path: Path):
    broken = tmp_path / "broken-skill"
    broken.mkdir()
    (broken / "config.yaml").write_text("name: broken\n", encoding="utf-8")
    with pytest.raises(SkillPackageError):
        validate_skill(broken)


def test_company_research_still_valid():
    bundled = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "ribhus"
        / "skills"
        / "bundled"
        / "company-research"
    )
    validate_skill(bundled)


def test_export_roundtrip_json(tmp_path: Path):
    memory = _memory(tmp_path)
    memory.remember_fact("Use IST")
    payload = memory.export()
    json.loads(json.dumps(payload))


def test_football_skill_package_and_triggers():
    bundled = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "ribhus"
        / "skills"
        / "bundled"
        / "football"
    )
    warnings = validate_skill(bundled)
    assert warnings == []
    skill = load_skill(bundled)
    assert skill.name == "football"
    assert skill.matches("What's happening with my football team?")
    assert skill.matches("ISL table")
    assert not skill.matches("Find me a hotel")
    assert "football_club" in skill.instructions
    assert "betting" in skill.instructions.lower()
    assert "LIVE" in skill.instructions
    assert "only links" in skill.instructions.lower()
    assert skill.matches("City match is going on live score")


def test_install_football_into_workspace(tmp_path: Path):
    skill, warnings = install_skill_with_warnings("football", workspace=tmp_path)
    assert skill.name == "football"
    assert (tmp_path / ".ribhus" / "skills" / "football" / "README.md").exists()
    assert (tmp_path / ".ribhus" / "skills" / "football" / "tools.py").exists()
    registry = SkillRegistry.load_default(tmp_path)
    assert "football" in registry.names()
    _ = warnings


def test_ensure_football_club_from_prompt_and_episodes(tmp_path: Path):
    from ribhus.memory.football import (
        ensure_football_club,
        get_saved_football_club,
    )

    memory = _memory(tmp_path)
    assert ensure_football_club(memory, prompt="I support Manchester City") == (
        "Manchester City"
    )
    assert get_saved_football_club(memory) == "Manchester City"

    other = _memory(tmp_path / "b")
    other.record_episode(
        "whats score of my football team",
        "Manchester City leads Norwich 2-0",
        skills=["football"],
    )
    other.record_episode(
        "who scored",
        "Cherki scored for Manchester City",
        skills=["football"],
    )
    assert ensure_football_club(other, prompt="which football team i support") == (
        "Manchester City"
    )
    assert "Manchester City" in (other.prompt_addon() or "")


def test_extract_prefs_language_city_budget(tmp_path: Path):
    memory = _memory(tmp_path)
    labels = memory.extract_and_persist(
        "I live in Pune and prefer Hinglish. Budget under ₹8000."
    )
    assert any("language" in x for x in labels)
    assert any("home_city" in x for x in labels)
    assert any("budget" in x for x in labels)
    addon = memory.prompt_addon("what language should you use?")
    assert "Pinned" in addon or "Hinglish" in addon
    assert "language" in " ".join(memory.last_injected)


def test_fts_search_and_forget(tmp_path: Path):
    memory = _memory(tmp_path)
    memory.remember_fact("Favourite football club: Arsenal", key="football_club")
    memory.remember_fact("Prefer English replies", key="language")
    hits = memory.search("Arsenal")
    assert any("Arsenal" in h.content for h in hits)
    msg = memory.forget("football_club")
    assert "Deleted" in msg
    assert memory.search("Arsenal") == [] or not any(
        h.key == "football_club" for h in memory.search("Arsenal")
    )


def test_episode_prune(tmp_path: Path):
    memory = MemoryService.from_path(
        tmp_path / "memory.sqlite", episode_keep=3
    )
    for i in range(5):
        memory.record_episode(f"task {i}", f"outcome {i}")
    assert len(memory.list(kind="episodic", limit=20)) == 3


@pytest.mark.asyncio
async def test_agent_auto_persists_prefs(tmp_path: Path):
    from ribhus.tools.registry import ToolRegistry

    memory = _memory(tmp_path)

    class FakeModel:
        async def generate(self, messages, tools=None):
            return ModelResponse(
                text="Ok, will use Hinglish.", tool_calls=[], raw=None
            )

    agent = Agent(
        model=FakeModel(),  # type: ignore[arg-type]
        tools=ToolRegistry(),
        max_iterations=3,
        memory=memory,
    )
    await agent.run("Please prefer Hinglish from now on")
    langs = [r for r in memory.list(kind="semantic") if r.key == "language"]
    assert langs
    assert "Hinglish" in langs[0].content


def test_default_registry_has_forget(tmp_path: Path):
    memory = _memory(tmp_path)
    names = default_registry(tmp_path, memory=memory).names()
    assert "memory_forget" in names
