from __future__ import annotations

from ribhus.eval.harness import bundled_skill, temp_workspace
from ribhus.eval.models import EvalCase
from ribhus.skills.installer import install_skill, remove_skill
from ribhus.skills.loader import load_skill
from ribhus.skills.package import validate_skill
from ribhus.skills.registry import SkillRegistry

_COMPANY = "Research this Indian company: Zoho"
_TRAVEL = "Find me a hotel in Goa under ₹8,000 for Friday and Saturday."
_FOOTBALL = "What's happening with my football team?"
_WEATHER = "what is the weather in Goa"


def _bundled_registry() -> SkillRegistry:
    return SkillRegistry(
        [
            load_skill(bundled_skill("company-research")),
            load_skill(bundled_skill("travel")),
            load_skill(bundled_skill("football")),
        ]
    )


def company_research_matches() -> None:
    skill = load_skill(bundled_skill("company-research"))
    assert skill.matches(_COMPANY)
    addon = SkillRegistry([skill]).prompt_addon(_COMPANY)
    assert "Active skills" in addon
    assert "company-research" in addon
    assert "Company brief" in skill.instructions or "Snapshot" in skill.instructions


def travel_matches_and_does_not_book() -> None:
    skill = load_skill(bundled_skill("travel"))
    assert skill.matches(_TRAVEL)
    text = skill.instructions.lower()
    assert "does not" in text
    assert "book" in text
    warnings = validate_skill(bundled_skill("travel"))
    assert isinstance(warnings, list)


def football_matches() -> None:
    skill = load_skill(bundled_skill("football"))
    assert skill.matches(_FOOTBALL)
    assert skill.matches("live score")


def weather_matches_none() -> None:
    registry = _bundled_registry()
    assert registry.match(_WEATHER) == []
    addon = registry.prompt_addon(_WEATHER)
    assert "Available skills" in addon
    assert "Active skills" not in addon


def install_and_remove() -> None:
    with temp_workspace() as workspace:
        skill = install_skill("travel", workspace=workspace)
        dest = workspace / ".ribhus" / "skills" / "travel"
        assert skill.name == "travel"
        assert dest.exists()
        assert (dest / "README.md").exists()
        remove_skill("travel", workspace=workspace)
        assert not dest.exists()


def validate_bundled() -> None:
    for name in ("company-research", "travel", "football"):
        warnings = validate_skill(bundled_skill(name))
        assert isinstance(warnings, list)


CASES = [
    EvalCase(
        "skills-company-research",
        "skills",
        "company-research",
        "Hero prompt matches and injects",
        company_research_matches,
    ),
    EvalCase(
        "skills-travel",
        "skills",
        "travel",
        "Goa hotel prompt; does not book",
        travel_matches_and_does_not_book,
    ),
    EvalCase(
        "skills-football",
        "skills",
        "football",
        "Football briefing trigger",
        football_matches,
    ),
    EvalCase(
        "skills-weather-none",
        "skills",
        "registry",
        "Weather matches no bundled skill",
        weather_matches_none,
    ),
    EvalCase(
        "skills-install-remove",
        "skills",
        "installer",
        "Install copies to .ribhus/skills",
        install_and_remove,
    ),
    EvalCase(
        "skills-validate",
        "skills",
        "package",
        "Bundled skills validate",
        validate_bundled,
    ),
]
