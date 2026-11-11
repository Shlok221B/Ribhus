from __future__ import annotations

from ribhus.eval.harness import bundled_skill
from ribhus.eval.models import EvalCase
from ribhus.skills.loader import load_skill


def travel_rupee_and_languages() -> None:
    skill = load_skill(bundled_skill("travel"))
    langs = {lang.lower() for lang in skill.config.languages}
    assert "hi" in langs or "hinglish" in langs
    assert "₹" in skill.instructions or "₹" in skill.config.description


def company_mca_cin() -> None:
    skill = load_skill(bundled_skill("company-research"))
    triggers = [t.lower() for t in skill.config.triggers]
    assert any("mca" in t for t in triggers)
    assert any("cin" in t for t in triggers)


def football_ist_isl() -> None:
    skill = load_skill(bundled_skill("football"))
    blob = (
        skill.instructions
        + " "
        + skill.config.description
        + " "
        + " ".join(skill.config.triggers)
    ).lower()
    assert "ist" in blob
    assert "isl" in blob


def job_search_deep_triggers() -> None:
    skill = load_skill(bundled_skill("job-search"))
    triggers = [t.lower() for t in skill.config.triggers]
    assert any("job" in t for t in triggers)
    blob = (skill.instructions + " " + skill.config.description).lower()
    assert "browser" in blob
    assert "web_search" in blob


def hinglish_on_bundled() -> None:
    for name in ("company-research", "travel", "football", "job-search"):
        skill = load_skill(bundled_skill(name))
        langs = {lang.lower() for lang in skill.config.languages}
        assert langs & {"hi", "hinglish"}, f"{name} missing Hindi/Hinglish: {langs}"


CASES = [
    EvalCase("india-travel-rupee", "india", "travel", "Travel uses ₹ and Indic languages", travel_rupee_and_languages),
    EvalCase("india-company-mca", "india", "company-research", "MCA/CIN triggers", company_mca_cin),
    EvalCase("india-football-ist", "india", "football", "Football briefing uses IST/ISL", football_ist_isl),
    EvalCase("india-job-search-deep", "india", "job-search", "Job search skill is deep+browser", job_search_deep_triggers),
    EvalCase("india-hinglish", "india", "skills", "Bundled skills declare Hinglish/Hindi", hinglish_on_bundled),
]
