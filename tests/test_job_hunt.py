"""Job hunt extract, fact lock, store, and dashboard API."""

from __future__ import annotations

from pathlib import Path

import pytest

from ribhus.channels.gmail_web.policy import EmailPolicyError
from ribhus.jobs.errors import JobHuntError
from ribhus.jobs.extract import (
    assert_public_job_url,
    company_slug,
    draft_email,
    extract_emails,
    extract_keywords,
    parse_role_company,
)
from ribhus.jobs.service import JobHuntService
from ribhus.jobs.store import JobStore
from ribhus.jobs.tailor import assert_facts_preserved, strip_latex_fence


BASE_TEX = r"""
\documentclass{article}
\begin{document}
\section{Experience}
Acme role, 2022--2024. Reach me at ada@example.com.
\end{document}
"""


def test_parse_posting_bits():
    title, company = parse_role_company(
        "Senior Engineer at Stripe | Greenhouse",
        "ignored",
    )
    assert title == "Senior Engineer"
    assert company == "Stripe"
    emails = extract_emails(
        "Write talent@stripe.com or noreply@stripe.com. Also privacy@stripe.com is noise? "
        "noreply skipped. talent stays."
    )
    assert emails[0] == "talent@stripe.com"
    assert "noreply@stripe.com" not in emails
    words = extract_keywords(
        "Requirements\nPython, Kubernetes, and Python for the platform team.",
    )
    assert any(word.lower() == "python" for word in words)
    assert any(word.lower() == "kubernetes" for word in words)
    assert company_slug("Stripe, Inc.") == "stripe_inc"


def test_rejects_local_job_urls():
    with pytest.raises(JobHuntError):
        assert_public_job_url("http://127.0.0.1/jobs/1")
    with pytest.raises(JobHuntError):
        assert_public_job_url("file:///tmp/job.html")


def test_fact_lock_keeps_dates_and_email():
    tailored = BASE_TEX.replace("Acme role", "Platform role")
    assert_facts_preserved(BASE_TEX, tailored)
    with pytest.raises(JobHuntError):
        assert_facts_preserved(BASE_TEX, tailored.replace("2022", "2019").replace("2024", "2020"))
    assert strip_latex_fence("```latex\n\\documentclass{article}\n```") == r"\documentclass{article}"


def test_ashby_paste_is_not_a_location_role():
    pasted = """Location
Remote (US)

Department
Engineering

Overview
Crux is the capital platform for the clean economy.

About the role
We have built products that finance clean energy.
"""
    role, company = parse_role_company("Location", pasted)
    assert company == "Crux"
    assert role != "Location"
    assert "Engineering" in role or role == "Role"


def test_name_from_bfseries_header():
    from ribhus.jobs.extract import applicant_name, resume_summary_sentence

    tex = r"""
\documentclass{article}
\begin{document}
{\fontsize{17}{20}\selectfont\bfseries Kartik Patel}
Founding engineer building and operating AI products from concept to production.
\end{document}
"""
    assert applicant_name(tex) == "Kartik Patel"
    assert resume_summary_sentence(tex).startswith("Founding engineer")


def test_draft_is_a_short_cold_email():
    subject, body = draft_email(
        name="Kartik Patel",
        role="",
        company="Crux",
        summary="Founding engineer building and operating AI products from concept to production.",
        department="Engineering",
        highlights=[
            "Owned Skitre.ai's audio and video practice simulation for customer conversations, sales, public speaking, and interviews, in a portfolio that reached 1,000+ users and 3,000+ completed simulations.",
            "Led 5-6 people across frontend and design, and interviewed 500+ candidates.",
        ],
        portfolio="https://xp.kartikp36.in",
        job_text="Crux is the capital platform for the clean economy. We modernize capital raising.",
    )
    assert subject == "Could I help you build Crux?"
    assert body.startswith("Hi,")
    assert "Kartik Patel" in body
    assert "https://xp.kartikp36.in" in body
    assert body.strip().splitlines()[-1] == "Kartik Patel"
    assert "Would you be open to a short conversation?" in body
    assert "emphasizes" not in body
    assert "Location" not in body
    assert sum(1 for line in body.splitlines() if line.startswith("- ")) == 2
    words = len(body.replace("https://xp.kartikp36.in", " ").split())
    assert 60 <= words <= 150
    assert " 000+" not in body
    assert "simulation that reached 1,000+" in body
    assert "Skitre.ai's that" not in body


def test_store_roundtrip(tmp_path: Path):
    store = JobStore(tmp_path / "job_hunt")
    store.save_resume(BASE_TEX)
    assert store.resume_saved()
    with pytest.raises(JobHuntError):
        store.save_resume("not latex")
    record = store.create({"role": "Engineer", "status": "ready"})
    assert store.get(record["id"])["role"] == "Engineer"
    updated = store.update(record["id"], status="sent")
    assert updated["status"] == "sent"


@pytest.fixture
def jobs_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fastapi = pytest.importorskip("fastapi")
    assert fastapi
    from fastapi.testclient import TestClient

    from ribhus.web.app import create_app
    from ribhus.web.auth import get_session_token
    from ribhus.web.task_store import TaskStore

    home = tmp_path / "ws"
    home.mkdir()
    (home / ".ribhus").mkdir()
    monkeypatch.chdir(home)
    monkeypatch.setenv("RIBHUS_WORKSPACE", str(home))
    monkeypatch.setenv("RIBHUS_API_KEY", "")
    monkeypatch.setenv("RIBHUS_MEMORY_ENABLED", "false")
    monkeypatch.setenv("RIBHUS_MCP_ENABLED", "false")
    store = TaskStore(home / ".ribhus" / "tasks.json")
    app = create_app(task_store=store)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {get_session_token()}"}
    return client, headers, home


def test_jobs_api_prepare(jobs_env, monkeypatch: pytest.MonkeyPatch):
    client, headers, home = jobs_env

    async def fake_fetch(_url: str):
        text = (
            "Requirements\nBuild services with Python and Kubernetes. "
            "Contact talent@acme.test for this Senior Engineer at Acme role. "
        )
        return "Senior Engineer at Acme", text + ("detail " * 20)

    async def fake_tailor(tex: str, **_kwargs):
        return tex, "Kept the base resume."

    def fake_compile(_tex_path: Path, pdf_path: Path):
        pdf_path.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr("ribhus.jobs.service.fetch_job_page", fake_fetch)
    monkeypatch.setattr("ribhus.jobs.service.tailor_resume", fake_tailor)
    monkeypatch.setattr("ribhus.jobs.service.compile_resume", fake_compile)

    denied = client.get("/api/jobs/status")
    assert denied.status_code == 401

    saved = client.put(
        "/api/jobs/resume",
        headers=headers,
        json={"tex": BASE_TEX},
    )
    assert saved.status_code == 200

    created = client.post(
        "/api/jobs/applications",
        headers=headers,
        json={"url": "https://jobs.acme.test/engineer"},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["company"] == "Acme"
    assert body["to"] == "talent@acme.test"
    assert body["status"] == "ready"
    assert body["pdf_ready"] is True
    assert (home / ".ribhus" / "job_hunt" / "apps" / body["id"] / body["pdf_file"]).is_file()

    pdf = client.get(f"/api/jobs/applications/{body['id']}/pdf", headers=headers)
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")


def test_jobs_api_pasted_description(jobs_env, monkeypatch: pytest.MonkeyPatch):
    client, headers, _home = jobs_env

    async def fail_fetch(_url: str):
        raise AssertionError("pasted description should not fetch the link")

    async def fake_tailor(tex: str, **_kwargs):
        return tex, "Kept the base resume."

    def fake_compile(_tex_path: Path, pdf_path: Path):
        pdf_path.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr("ribhus.jobs.service.fetch_job_page", fail_fetch)
    monkeypatch.setattr("ribhus.jobs.service.tailor_resume", fake_tailor)
    monkeypatch.setattr("ribhus.jobs.service.compile_resume", fake_compile)

    client.put("/api/jobs/resume", headers=headers, json={"tex": BASE_TEX})
    created = client.post(
        "/api/jobs/applications",
        headers=headers,
        json={
            "url": "https://www.linkedin.com/jobs/view/1",
            "text": (
                "Senior Engineer at Acme\n\n"
                "Requirements\nPython and Kubernetes. Write talent@acme.test. "
                + ("platform " * 20)
            ),
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["company"] == "Acme"
    assert body["to"] == "talent@acme.test"
    assert body["url"] == "https://www.linkedin.com/jobs/view/1"
    assert body["status"] == "ready"


def test_send_uses_approved_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    service = JobHuntService(tmp_path / "job_hunt")
    service.save_resume(BASE_TEX)
    record = service.store.create(
        {
            "pdf_file": "resume_acme.pdf",
            "pdf_ready": True,
            "status": "ready",
            "error": "",
        }
    )
    folder = service.store.folder(record["id"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "resume_acme.pdf").write_bytes(b"%PDF")

    captured: dict[str, object] = {}

    class FakeSender:
        def __init__(self, _session: object) -> None:
            return None

        async def send_new(self, **kwargs: object) -> None:
            captured.update(kwargs)

    class FakePolicy:
        def assert_can_send(self, *_args: object) -> None:
            return None

        def record_send(self, *_args: object) -> None:
            return None

    monkeypatch.setattr("ribhus.jobs.service.GmailSender", FakeSender)
    import asyncio

    sent = asyncio.run(
        service.send(
            record["id"],
            to="talent@acme.test",
            subject="Engineer",
            body="Hello",
            session=object(),  # type: ignore[arg-type]
            policy=FakePolicy(),  # type: ignore[arg-type]
        )
    )
    assert sent["status"] == "sent"
    assert captured["to"] == "talent@acme.test"
    assert str(captured["attachment"]).endswith("resume_acme.pdf")

    class RefusePolicy:
        def assert_can_send(self, *_args: object) -> None:
            raise EmailPolicyError("rate limit")

        def record_send(self, *_args: object) -> None:
            return None

    again = service.store.create(
        {
            "pdf_file": "resume_acme.pdf",
            "pdf_ready": True,
            "status": "ready",
            "error": "",
        }
    )
    (service.store.folder(again["id"]) / "resume_acme.pdf").write_bytes(b"%PDF")
    with pytest.raises(JobHuntError, match="rate limit"):
        asyncio.run(
            service.send(
                again["id"],
                to="talent@acme.test",
                subject="Engineer",
                body="Hello",
                session=object(),  # type: ignore[arg-type]
                policy=RefusePolicy(),  # type: ignore[arg-type]
            )
        )
