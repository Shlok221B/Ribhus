"""Phase 6: persistence, metrics payload, research API."""

from __future__ import annotations

from pathlib import Path

import pytest

from ribhus.research.models import (
    EvaluationResult,
    JobRecord,
    JobVerification,
    ResearchMetrics,
    ResearchPlan,
    SearchLead,
)
from ribhus.research.store import ResearchStore
from ribhus.research.synthesizer import _jobs_data_fence

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ribhus.web.app import create_app
from ribhus.web.auth import get_session_token
from ribhus.web.task_store import TaskStore


def test_store_roundtrip_with_fingerprints_and_detail(tmp_path: Path):
    store = ResearchStore(tmp_path / "research.sqlite")
    plan = ResearchPlan(
        objective="Find Python jobs in Pune",
        constraints={"role": "Python Backend Developer", "location": "Pune"},
        domain="jobs",
    )
    run_id = store.create_run(
        objective=plan.objective, task_id="task_abc", plan=plan
    )
    store.add_queries(run_id, 1, ["python backend pune"], fingerprints=["fp1"])
    store.add_leads(
        run_id,
        1,
        [
            SearchLead(
                title="Role",
                url="https://boards.greenhouse.io/acme/jobs/1",
                canonical_url="https://boards.greenhouse.io/acme/jobs/1",
                provider="ddgs",
                score=0.9,
            )
        ],
    )
    record = JobRecord(
        company="Acme",
        role="Python Backend Developer",
        location="Pune",
        job_url="https://boards.greenhouse.io/acme/jobs/1",
        application_url="https://boards.greenhouse.io/acme/jobs/1/apply",
        status="application_accessible",
        verification=JobVerification(
            job_page_accessible=True,
            application_link_found=True,
            application_page_accessible=True,
        ),
    )
    store.replace_records(run_id, [record])
    evaluation = EvaluationResult(
        research_complete=True,
        completion_score=80,
        stop_reason="quality_met",
        quality_met=True,
    )
    store.add_iteration(run_id, 1, evaluation)
    metrics = ResearchMetrics(
        iterations=1,
        urls_investigated=1,
        records_kept=1,
        leads_discovered=1,
        queries_run=1,
        duplicate_rate=0.0,
        constraint_satisfaction=1.0,
        execution_time_seconds=1.2,
    )
    store.update_run(
        run_id,
        status="completed",
        plan=plan,
        evaluation=evaluation,
        metrics=metrics,
        usage={"total_tokens": 100},
        summary="done",
        incomplete=False,
    )

    latest = store.latest_for_task("task_abc")
    assert latest is not None
    assert latest["id"] == run_id

    detail = store.get_run_detail(run_id)
    assert detail is not None
    assert detail["plan"]["domain"] == "jobs"
    assert detail["evaluation"]["quality_met"] is True
    assert detail["metrics"]["urls_investigated"] == 1
    assert len(detail["queries"]) == 1
    assert len(detail["leads"]) == 1
    assert len(detail["records"]) == 1
    assert detail["records"][0]["fingerprint"]
    assert detail["iterations"][0]["evaluation"]["stop_reason"] == "quality_met"
    assert store.list_recent(limit=5)[0]["id"] == run_id


def test_jobs_fence_includes_metrics_and_stop_reason():
    plan = ResearchPlan(
        objective="Find Python Backend Developer jobs in Pune",
        constraints={"role": "Python Backend Developer", "location": "Pune"},
        domain="jobs",
    )
    metrics = ResearchMetrics(
        iterations=2,
        urls_investigated=12,
        duplicate_rate=0.1,
        execution_time_seconds=9.5,
        average_research_cost_usd=0.02,
        total_tokens=4000,
        constraint_satisfaction=0.8,
    )
    evaluation = EvaluationResult(
        research_complete=True,
        completion_score=72,
        quality_met=False,
        stop_reason="max_iterations",
    )
    fence = _jobs_data_fence(
        plan.objective,
        plan,
        [],
        metrics,
        incomplete=True,
        evaluation=evaluation,
        stop_reason="max_iterations",
    )
    assert "ribhus-jobs" in fence
    assert '"stop_reason": "max_iterations"' in fence
    assert '"quality_met": false' in fence
    assert '"iterations": 2' in fence


@pytest.fixture
def dashboard_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "ws"
    home.mkdir()
    (home / ".ribhus").mkdir()
    monkeypatch.chdir(home)
    monkeypatch.setenv("RIBHUS_WORKSPACE", str(home))
    monkeypatch.setenv("RIBHUS_API_KEY", "test-key-not-real")
    monkeypatch.setenv("RIBHUS_MEMORY_ENABLED", "true")
    monkeypatch.setenv("RIBHUS_MCP_ENABLED", "false")
    store = TaskStore(home / ".ribhus" / "tasks.json")
    app = create_app(task_store=store)
    client = TestClient(app)
    token = get_session_token()
    headers = {"Authorization": f"Bearer {token}"}
    return client, headers, home


def test_research_api_list_and_get(dashboard_env):
    client, headers, home = dashboard_env
    store = ResearchStore(home / ".ribhus" / "research.sqlite")
    plan = ResearchPlan(objective="jobs", domain="jobs", constraints={"role": "Python"})
    run_id = store.create_run(objective="jobs", task_id="t1", plan=plan)
    store.update_run(
        run_id,
        status="completed",
        metrics=ResearchMetrics(iterations=1, records_kept=0),
        incomplete=False,
    )

    assert client.get("/api/research/runs").status_code == 401
    listed = client.get("/api/research/runs", headers=headers)
    assert listed.status_code == 200
    assert any(item["id"] == run_id for item in listed.json())

    detail = client.get(f"/api/research/runs/{run_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["run"]["id"] == run_id

    by_task = client.get("/api/research/by-task/t1", headers=headers)
    assert by_task.status_code == 200
    assert by_task.json()["run"]["id"] == run_id

    missing = client.get("/api/research/by-task/nope", headers=headers)
    assert missing.status_code == 404
