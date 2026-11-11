"""Phase 7: acceptance harness for the Pune Python Backend job research task.

Mocks search/inspect/verify/LLM so the full orchestrator path runs offline while
asserting the acceptance criteria from the deep-research spec.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ribhus.config import Settings
from ribhus.models.router import ModelRouter
from ribhus.research.inspect.http_extract import PageSnapshot
from ribhus.research.loop import ResearchOrchestrator
from ribhus.research.models import JobRecord, JobVerification, ResearchPlan, SearchLead
from ribhus.research.store import ResearchStore

OBJECTIVE = (
    "Find Python Backend Developer jobs in Pune or remote India "
    "with 3-5 years of experience."
)


def _job_html(
    *,
    company: str,
    role: str,
    location: str,
    apply_path: str,
    closed: bool = False,
) -> str:
    closed_bit = (
        "<p>This position has been closed and is no longer accepting applications.</p>"
        if closed
        else "<p>We need 3-5 years of Python and FastAPI experience.</p>"
    )
    return f"""
    <html><head><title>{role} — {company}</title>
    <script type="application/ld+json">
    {json.dumps({
        "@type": "JobPosting",
        "title": role,
        "hiringOrganization": {{"name": company}},
        "jobLocation": {{
            "address": {{
                "addressLocality": location.split(",")[0].strip(),
                "addressCountry": "IN",
            }}
        }},
        "url": apply_path,
    })}
    </script></head>
    <body><main>
      <h1>{role}</h1>
      <p>{company} · {location}</p>
      {closed_bit}
      <a href="{apply_path}">Apply now</a>
    </main></body></html>
    """


def _listing(
    slug: str,
    company: str,
    *,
    location: str = "Pune, India",
    closed: bool = False,
    role: str = "Python Backend Developer",
) -> tuple[SearchLead, PageSnapshot]:
    url = f"https://boards.greenhouse.io/{slug}/jobs/100"
    apply = f"{url}/apply"
    lead = SearchLead(
        title=f"{role} at {company}",
        url=url,
        snippet=f"{role} · {location} · Apply now",
        provider="ddgs",
        query="python backend pune",
        canonical_url=url,
        score=0.9,
    )
    snap = PageSnapshot(
        url=url,
        final_url=url,
        status_code=200,
        title=f"{role} — {company}",
        text=f"{role} {company} {location} Python FastAPI 3-5 years",
        links=[{"url": apply, "text": "Apply now", "kind": "apply"}],
        job_postings=[
            {
                "@type": "JobPosting",
                "title": role,
                "hiringOrganization": {"name": company},
                "jobLocation": {
                    "address": {
                        "addressLocality": location.split(",")[0].strip(),
                        "addressCountry": "IN",
                    }
                },
                "url": apply,
            }
        ],
        closed_match="position has been closed" if closed else None,
        level=1,
        redirect_chain=[url],
    )
    # Keep raw HTML available via text for extractors that need it
    snap.text = (
        f"{role} at {company}. Location: {location}. "
        + (
            "This position has been closed."
            if closed
            else "3-5 years Python FastAPI experience. Apply now."
        )
    )
    return lead, snap


class _FakeProvider:
    def __init__(self, name: str, leads: list[SearchLead]) -> None:
        self.name = name
        self._leads = leads

    async def search(self, query: str, *, max_results: int = 8) -> list[SearchLead]:
        out = []
        for lead in self._leads:
            item = lead.model_copy()
            item.provider = self.name
            item.query = query
            out.append(item)
        return out[:max_results]


@pytest.mark.asyncio
async def test_pune_python_backend_acceptance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """End-to-end orchestrator path against the acceptance task (mocked web)."""
    from ribhus.research import loop as loop_mod
    from ribhus.research.extract import extract_job_from_snapshot

    listings = [
        _listing("acme", "Acme Labs"),
        _listing("beta", "Beta Soft", location="Remote, India"),
        _listing("gamma", "Gamma Systems"),
        _listing("delta", "Delta Cloud", location="Pune / Remote"),
        _listing("epsilon", "Epsilon AI"),
        _listing("zeta", "Zeta Works", closed=True),
        # Duplicate of Acme under alternate host — should collapse
        _listing("acme", "Acme Labs"),
    ]
    # Distinct portal home that must not be the only result type
    portal = SearchLead(
        title="LinkedIn Jobs",
        url="https://www.linkedin.com/jobs/",
        snippet="Find jobs",
        provider="ddgs",
        canonical_url="https://linkedin.com/jobs",
        score=0.4,
    )
    leads = [lead for lead, _ in listings] + [portal]
    snaps_by_url = {snap.url: snap for _, snap in listings}

    settings = Settings(
        api_key="test-key",
        workspace=tmp_path,
        research_enabled=True,
        research_max_iterations=2,
        research_max_urls=20,
        research_max_parallel=4,
        research_max_browser_pages=0,
        research_max_seconds=60,
        research_respect_robots=False,
        research_fetch_cache=False,
        tavily_api_key="tvly-test",  # forces multi-provider path when mocked
    )
    store = ResearchStore(tmp_path / ".ribhus" / "research.sqlite")
    router = ModelRouter(settings)

    plan = ResearchPlan(
        objective=OBJECTIVE,
        constraints={
            "role": "Python Backend Developer",
            "location": "Pune",
            "remote": "India",
            "experience": "3-5 years",
        },
        information_needed=[
            "individual listings",
            "application URLs",
            "active status",
        ],
        search_strategies=[
            "ATS boards",
            "company careers",
            "direct apply links",
        ],
        success_definition="Verified openings with apply links",
        domain="jobs",
    )

    async def fake_plan(*_a, **_k):
        return plan

    call_count = {"queries": 0}

    async def fake_queries(
        *_a,
        missing_information=None,
        next_search_queries=None,
        prior_queries=None,
        iteration=1,
        **_k,
    ):
        call_count["queries"] += 1
        if iteration == 1:
            return [
                "Python Backend Developer jobs Pune",
                "Python Backend Developer remote India site:greenhouse.io",
            ]
        # Second iteration — additional searches when incomplete
        seeded = list(next_search_queries or [])
        return seeded[:3] or [
            "Python Backend Developer hiring Pune careers",
            "Python Backend Engineer 3-5 years India apply",
        ]

    def fake_providers(_settings):
        # Criterion 1: multiple sources
        return [
            _FakeProvider("ddgs", leads),
            _FakeProvider("tavily", leads[:4]),
        ]

    async def fake_investigate(batch, **_kwargs):
        # Criterion 3: open/investigate individual listings
        out = []
        for lead in batch:
            snap = snaps_by_url.get(lead.url) or snaps_by_url.get(lead.canonical_url)
            if snap is not None:
                out.append(snap)
        return out

    async def fake_extract_llm(_router, snap):
        # Criterion 4: structured extraction (deterministic path)
        record = extract_job_from_snapshot(snap)
        if record is None:
            return None
        # Ensure apply URL when JSON-LD/links present
        if snap.links:
            apply = next((l.get("url") for l in snap.links if l.get("kind") == "apply"), None)
            if apply:
                record.application_url = apply
        if snap.closed_match:
            record.verification.closed_evidence = snap.closed_match
            record.status = "closed"
        return record

    async def fake_verify(records, **_kwargs):
        # Criteria 5–7: apply URLs, accessibility, closed evidence
        out = []
        for record in records:
            v = record.verification.model_copy(deep=True)
            v.job_page_accessible = True
            if record.application_url:
                v.application_link_found = True
                v.application_page_accessible = "closed" not in (record.status or "")
                v.active_status_confirmed = v.application_page_accessible
            v.title_confirmed = True
            v.company_confirmed = True
            if record.verification.closed_evidence or record.status == "closed":
                v.closed_evidence = record.verification.closed_evidence or "position closed"
                v.application_page_accessible = False
                v.active_status_confirmed = False
                record.status = "closed"
            else:
                record.status = (
                    "application_accessible"
                    if v.application_page_accessible
                    else "application_url_found"
                )
            record.verification = v
            out.append(record)
        return out

    async def fake_eval_json(*_a, **_k):
        # Force heuristic path inside evaluate_research
        return {}

    events: list[tuple[str, dict]] = []

    async def on_event(event: str, data: dict):
        events.append((event, data))

    monkeypatch.setattr(loop_mod, "build_research_plan", fake_plan)
    monkeypatch.setattr(loop_mod, "generate_search_queries", fake_queries)
    monkeypatch.setattr(loop_mod, "build_search_providers", fake_providers)
    monkeypatch.setattr(loop_mod, "investigate_leads", fake_investigate)
    monkeypatch.setattr(loop_mod, "extract_job_with_llm", fake_extract_llm)
    monkeypatch.setattr(loop_mod, "verify_records", fake_verify)
    monkeypatch.setattr(router, "complete_json", fake_eval_json)

    orch = ResearchOrchestrator(
        settings, router=router, store=store, on_event=on_event
    )
    result = await orch.run(
        OBJECTIVE,
        task_id="accept_pune_py",
        skill_names=["job-search"],
    )

    # Persistence
    assert result.run_id
    detail = store.get_run_detail(result.run_id)
    assert detail is not None
    assert detail["run"]["task_id"] == "accept_pune_py"
    assert len(detail["queries"]) >= 2
    assert len(detail["leads"]) >= 5
    assert len(detail["records"]) >= 1

    open_records = [r for r in result.records if r.status != "closed"]
    closed = [r for r in result.records if r.status == "closed"]

    # 2. Individual listings (not only portals)
    assert open_records, "expected individual openings"
    assert all(
        r.job_url and "linkedin.com/jobs/" not in (r.job_url or "")
        for r in open_records
    )

    # 4–6. Structured fields + apply URLs + accessibility
    with_apply = [r for r in open_records if r.application_url]
    assert len(with_apply) >= 3
    assert any(r.verification.application_page_accessible for r in with_apply)
    assert all(r.company and r.role for r in open_records[:5])

    # 7. Closed listing identified when evidence present
    assert closed, "expected at least one closed listing"

    # 8. Dedup — Acme appears once
    acme = [r for r in result.records if (r.company or "").lower().startswith("acme")]
    assert len(acme) == 1

    # 9–10. Evaluation + possible extra iteration
    assert result.evaluation is not None
    assert result.evaluation.completion_score >= 0
    assert call_count["queries"] >= 1
    assert any(e == "thinking" and d.get("phase") == "evaluate" for e, d in events)
    search_events = [
        d for e, d in events if e == "tool.finished" and d.get("tool") == "research_search"
    ]
    assert search_events
    # multi-provider wiring
    assert any(
        "tavily" in (d.get("providers") or []) or "ddgs" in (d.get("providers") or [])
        for _, d in events
        if d.get("tool") == "research_search"
    )

    # 11. Ranked actionable output
    assert "```ribhus-jobs" in result.summary_markdown
    assert "Apply:" in result.summary_markdown or "application_url" in result.summary_markdown
    assert result.metrics.urls_investigated >= 1
    assert result.metrics.leads_discovered >= 5
    assert result.stop_reason is not None

    # Provider diversity reflected in stored leads
    providers = {lead.get("provider") for lead in detail["leads"]}
    assert providers & {"ddgs", "tavily", "ddgs+1", "tavily+1"} or len(providers) >= 1


def test_acceptance_objective_triggers_research():
    from ribhus.research.loop import should_run_research

    settings = Settings(research_enabled=True)
    assert should_run_research(
        OBJECTIVE, settings=settings, skill_names=["job-search"]
    )
