from ribhus.config import Settings
from ribhus.models.router import ModelRouter
from ribhus.research.loop import should_run_research
from ribhus.research.planner import _fallback_plan


def test_model_router_roles():
    settings = Settings(
        api_key="test",
        model="gpt-4o-mini",
        model_reasoning="gpt-4o",
        model_fast="gpt-4o-mini",
    )
    router = ModelRouter(settings)
    assert router.model_for("plan")[0] == "gpt-4o"
    assert router.model_for("extract")[0] == "gpt-4o-mini"
    assert router.model_for("evaluate")[0] == "gpt-4o"


def test_should_run_research_for_jobs_skill():
    settings = Settings(api_key="test", research_enabled=True)
    assert should_run_research(
        "hello", settings=settings, skill_names=["job-search"]
    )
    assert should_run_research(
        "Find Python backend developer jobs in Pune",
        settings=settings,
        skill_names=[],
    )
    assert not should_run_research(
        "calculate 2+2", settings=settings, skill_names=[]
    )


def test_fallback_plan_jobs():
    plan = _fallback_plan(
        "Find Python backend developer jobs in Pune with 3-5 years experience"
    )
    assert plan.domain == "jobs"
    assert plan.research_objectives
    assert any("greenhouse" in s.lower() or "ATS" in s or "Ashby" in s for s in plan.search_strategies) or len(
        plan.search_strategies
    ) >= 3
