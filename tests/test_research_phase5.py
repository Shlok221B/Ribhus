"""Phase 5: evaluator completeness + iterative stop reasons."""

from __future__ import annotations

import pytest

from ribhus.research.evaluator import (
    _dedupe_queries,
    _heuristic_eval,
    jobs_quality_met,
)
from ribhus.research.models import JobRecord, JobVerification, ResearchPlan, SearchLead


def _plan() -> ResearchPlan:
    return ResearchPlan(
        objective="Find Python Backend Developer jobs in Pune or remote India",
        constraints={
            "role": "Python Backend Developer",
            "location": "Pune",
            "experience": "3-5 years",
        },
        domain="jobs",
    )


def _record(
    *,
    company: str,
    role: str = "Python Backend Developer",
    location: str = "Pune, India",
    apply: bool = True,
    verified: bool = False,
    closed: bool = False,
) -> JobRecord:
    url = f"https://boards.greenhouse.io/{company.lower()}/jobs/{abs(hash(company)) % 10000}"
    apply_url = f"{url}/apply" if apply else None
    status = "closed" if closed else (
        "application_accessible" if verified else (
            "application_url_found" if apply else "accessible"
        )
    )
    return JobRecord(
        company=company,
        role=role,
        location=location,
        experience="3-5 years",
        job_url=url,
        application_url=apply_url,
        status=status,
        verification=JobVerification(
            job_page_accessible=not closed,
            application_link_found=apply,
            application_page_accessible=verified,
            active_status_confirmed=verified,
            title_confirmed=True,
            company_confirmed=True,
            closed_evidence="position closed" if closed else None,
        ),
        explicit_fields=["company", "role", "location"],
    )


def test_jobs_quality_met_requires_volume_and_verification():
    plan = _plan()
    thin = [_record(company=f"Co{i}") for i in range(3)]
    assert not jobs_quality_met(thin, plan)

    strong = [
        _record(company=f"Co{i}", apply=True, verified=i < 3)
        for i in range(6)
    ]
    assert jobs_quality_met(strong, plan)


def test_heuristic_stops_on_quality_and_max_iterations():
    plan = _plan()
    records = [
        _record(company=f"Co{i}", apply=True, verified=i < 3) for i in range(6)
    ]
    leads = [
        SearchLead(title="x", url=f"https://example.com/{i}", canonical_url=f"u{i}")
        for i in range(5)
    ]
    done = _heuristic_eval(plan, records, leads, iteration=1, max_iterations=3)
    assert done.quality_met is True
    assert done.research_complete is True
    assert done.stop_reason == "quality_met"

    thin = [_record(company="OnlyOne")]
    capped = _heuristic_eval(plan, thin, leads, iteration=3, max_iterations=3)
    assert capped.research_complete is True
    assert capped.quality_met is False
    assert capped.stop_reason == "max_iterations"
    assert capped.next_search_queries


def test_dedupe_queries_skips_prior_fingerprints():
    prior = ["Python Backend Developer jobs Pune"]
    next_q = _dedupe_queries(
        [
            "Python Backend Developer jobs Pune",
            "  python backend developer jobs pune  ",
            "Python Backend Engineer remote India",
        ],
        prior,
    )
    assert len(next_q) == 1
    assert "remote India" in next_q[0]


@pytest.mark.asyncio
async def test_evaluate_blends_llm_and_rejects_false_complete(monkeypatch):
    from ribhus.config import Settings
    from ribhus.models.router import ModelRouter
    from ribhus.research import evaluator as ev

    plan = _plan()
    thin = [_record(company="Only")]
    router = ModelRouter(Settings(api_key="x"))

    async def fake_json(*_a, **_k):
        return {
            "research_complete": True,
            "completion_score": 99,
            "missing_information": [],
            "next_search_queries": ["Python Backend Developer jobs Pune"],
            "next_actions": [],
            "rationale": "looks done",
        }

    monkeypatch.setattr(router, "complete_json", fake_json)
    result = await ev.evaluate_research(
        router,
        user_objective=plan.objective,
        plan=plan,
        queries=["Python Backend Developer jobs Pune"],
        leads=[],
        records=thin,
        iteration=1,
        max_iterations=3,
        new_leads_this_round=2,
    )
    assert result.quality_met is False
    assert result.research_complete is False
    assert result.completion_score <= 70
    assert result.next_search_queries  # still proposes new work
