"""Batch job hunt: split a link or paste, draft every opening, send one at a time."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from ribhus.channels.gmail_web.policy import EmailPolicy
from ribhus.jobs.errors import JobHuntError
from ribhus.jobs.service import JobHuntService, _wait_for_send
from ribhus.jobs.tailor import _summary_keeps_facts, explain_resume, reorder_skills
from ribhus.jobs.split import (
    blocks_around_urls,
    collect_openings,
    listing_job_urls,
    parse_model_openings,
    split_marked_sections,
)

BASE_TEX = r"""
\documentclass{article}
\begin{document}
\section{Experience}
Acme role, 2022--2024. Reach me at ada@example.com.
\end{document}
"""


def _long(title: str, email: str) -> str:
    body = "Requirements\n" + ("Own the sample platform and ship it to production. " * 6)
    return f"{title}\n\n{body}\nWrite {email}."


def test_explain_resume_names_the_summary_or_the_base_file():
    changed = BASE_TEX.replace(
        "Acme role, 2022--2024. Reach me at ada@example.com.",
        "Platform engineer shipping sample products from concept to production since 2022.",
    )
    note = explain_resume(BASE_TEX, changed)
    assert "Summary rewritten" in note
    assert "Before:" in note
    assert "After:" in note
    assert explain_resume(BASE_TEX, BASE_TEX).startswith("Base resume attached")


def test_summary_keeps_named_tools_and_rejects_new_ones():
    original = (
        "Founding engineer building and operating AI products from concept to production, "
        "who ships to real users and stays on them after launch. Experienced in React, Next.js, "
        "Django, and LLM and speech pipelines, with a focus on reliability, performance, and "
        "cost-quality trade-offs. Combines hands-on engineering with team leadership and "
        "customer-facing product execution, from pitches and demos to hiring and delivery."
    )
    invented = (
        "Product designer focused on building and operating AI products from concept to production "
        "using Figma and React. Experienced in developing mobile-ready interfaces with a focus on "
        "reliability, performance, and cost-quality trade-offs. Combines hands-on design execution "
        "with team leadership and customer-facing product delivery."
    )
    shifted = (
        "Founding engineer who ships React, Next.js, and Django AI products to real users and stays "
        "on them after launch. The work includes LLM and speech pipelines, with a focus on "
        "reliability, performance, and cost-quality trade-offs. Combines hands-on engineering with "
        "team leadership and customer-facing product execution, from pitches and demos to hiring "
        "and delivery."
    )
    assert not _summary_keeps_facts(original, invented)
    assert _summary_keeps_facts(original, shifted)


def test_reorder_skills_promotes_terms_from_the_posting():
    tex = "\n".join(
        [
            r"\skillrow{Languages}{TypeScript, JavaScript, Python}",
            r"\skillrow{Backend}{Redis, Django}",
            r"\skillrow{Spoken}{English, Hindi}",
        ]
    )
    moved = reorder_skills(tex, "Build Django services for the API.", ["Django"])
    assert "Rust" not in moved
    assert r"\skillrow{Backend}{Django, Redis}" in moved
    assert moved.index("Backend") < moved.index("Languages")
    note = explain_resume(tex, moved)
    assert "No skills were added" in note
    assert "Django" in note
    items = reorder_skills(
        r"\skillrow{Languages}{TypeScript, JavaScript, Python}",
        "Python services",
        [],
    )
    assert items.startswith(r"\skillrow{Languages}{Python, TypeScript, JavaScript}")
    java = reorder_skills(
        r"\skillrow{Languages}{Java, JavaScript, Python}",
        "JavaScript product work",
        [],
    )
    assert java.startswith(r"\skillrow{Languages}{JavaScript, Java, Python}")
    spoken = "\n".join(
        [
            r"\skillrow{Spoken}{English, Hindi, and Gujarati}",
            r"\skillrow{Languages}{TypeScript, Python}",
        ]
    )
    kept = reorder_skills(spoken, "We need Python and Django.", [])
    assert kept.index("Languages") < kept.index("Spoken")
    assert r"\skillrow{Spoken}{English, Hindi, and Gujarati}" in kept


def test_split_on_separator_and_ignore_short_chunks():
    text = "\n---\n".join(
        [
            "too short",
            _long("Senior Engineer at Acme", "talent@acme.test"),
            _long("Designer at Nimbus", "jobs@nimbus.test"),
        ]
    )
    blocks = split_marked_sections(text)
    assert [block["title"] for block in blocks] == [
        "Senior Engineer at Acme",
        "Designer at Nimbus",
    ]


def test_blocks_around_urls_keep_the_description_with_each_link():
    first = _long("Senior Engineer at Acme", "talent@acme.test")
    second = _long("Designer at Nimbus", "jobs@nimbus.test")
    text = f"{first}\nhttps://jobs.acme.test/engineer\n\n{second}\nhttps://jobs.nimbus.test/designer\n"
    blocks = blocks_around_urls(text)
    assert len(blocks) == 2
    assert blocks[0]["url"] == "https://jobs.acme.test/engineer"
    assert "Senior Engineer at Acme" in blocks[0]["text"]
    assert "Designer at Nimbus" not in blocks[0]["text"]
    assert blocks[1]["url"] == "https://jobs.nimbus.test/designer"
    assert "Designer at Nimbus" in blocks[1]["text"]


def test_listing_links_stay_on_the_board_and_known_ats():
    html = """
    <html><body>
      <a href="/jobs/engineer">Engineer</a>
      <a href="https://jobs.example.test/jobs/engineer">Same</a>
      <a href="/jobs/designer">Designer</a>
      <a href="/about">About</a>
      <a href="https://evil.test/jobs/nope">Off site</a>
      <a href="https://boards.greenhouse.io/acme/jobs/99">Greenhouse</a>
    </body></html>
    """
    found = listing_job_urls(html, "https://jobs.example.test/jobs")
    assert found == [
        "https://jobs.example.test/jobs/engineer",
        "https://jobs.example.test/jobs/designer",
        "https://boards.greenhouse.io/acme/jobs/99",
    ]


def test_model_split_drops_invented_email_and_single_opening():
    raw = json.dumps(
        {
            "openings": [
                {
                    "role": "Engineer",
                    "company": "Acme",
                    "email": "talent@acme.test",
                    "text": _long("Engineer", "talent@acme.test"),
                },
                {
                    "role": "Designer",
                    "company": "Nimbus",
                    "email": "invented@nimbus.test",
                    "text": _long("Designer", "jobs@nimbus.test"),
                },
            ]
        }
    )
    openings = parse_model_openings(raw)
    assert len(openings) == 2
    assert openings[0]["email"] == "talent@acme.test"
    assert openings[1]["email"] == ""
    assert parse_model_openings('{"openings": []}') == []


def test_collect_fetches_a_bare_link_list_and_caps_the_batch():
    calls: list[str] = []

    async def fetch(url: str):
        calls.append(url)
        text = _long("Senior Engineer at Acme", "talent@acme.test")
        return "Senior Engineer at Acme", text, "<html></html>", url

    urls = [f"https://jobs.acme.test/{index}" for index in range(12)]
    openings, omitted, note = asyncio.run(
        collect_openings("", "\n".join(urls), fetch=fetch)
    )
    assert len(openings) == 10
    assert omitted == 2
    assert len(calls) == 10
    assert "Left out 2" in note


def test_collect_reads_postings_linked_from_a_board():
    listing = """
    <html><body>
      <a href="https://jobs.acme.test/jobs/one">One</a>
      <a href="https://jobs.acme.test/jobs/two">Two</a>
    </body></html>
    """

    async def fetch(url: str):
        if url.endswith("/careers"):
            return "Careers", "A board of roles and not much else. " * 4, listing, url
        title = "Senior Engineer at Acme" if url.endswith("/one") else "Designer at Nimbus"
        email = "talent@acme.test" if url.endswith("/one") else "jobs@nimbus.test"
        return title, _long(title, email), "<html></html>", url

    openings, omitted, _note = asyncio.run(
        collect_openings("https://jobs.acme.test/careers", "", fetch=fetch)
    )
    assert omitted == 0
    assert [item["url"] for item in openings] == [
        "https://jobs.acme.test/jobs/one",
        "https://jobs.acme.test/jobs/two",
    ]


@pytest.fixture
def jobs_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("fastapi")
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


def test_batch_prepares_one_pdf_and_two_drafts(jobs_env, monkeypatch: pytest.MonkeyPatch):
    client, headers, home = jobs_env
    compiles: list[Path] = []

    def fake_compile(_tex_path: Path, pdf_path: Path):
        compiles.append(pdf_path)
        pdf_path.write_bytes(b"%PDF-batch")

    async def fake_collect(_url: str, _text: str, **_kwargs):
        return (
            [
                {
                    "url": "https://jobs.acme.test/engineer",
                    "title": "Senior Engineer at Acme",
                    "text": _long("Senior Engineer at Acme", "talent@acme.test"),
                },
                {
                    "url": "https://jobs.nimbus.test/designer",
                    "title": "Designer at Nimbus",
                    "text": _long("Designer at Nimbus", "jobs@nimbus.test"),
                },
            ],
            1,
            "Prepared the first 10. Left out 1.",
        )

    monkeypatch.setattr("ribhus.jobs.service.compile_resume", fake_compile)
    monkeypatch.setattr("ribhus.jobs.service.collect_openings", fake_collect)

    client.put("/api/jobs/resume", headers=headers, json={"tex": BASE_TEX})
    created = client.post(
        "/api/jobs/batches",
        headers=headers,
        json={"text": _long("Senior Engineer at Acme", "talent@acme.test") + "\n---\n" + _long("Designer at Nimbus", "jobs@nimbus.test")},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["omitted"] == 1
    assert len(compiles) == 3
    apps = body["applications"]
    assert len(apps) == 2
    assert apps[0]["to"] == "talent@acme.test"
    assert apps[1]["to"] == "jobs@nimbus.test"
    assert apps[0]["pdf_file"] == "resume_acme.pdf"
    assert apps[1]["pdf_file"] == "resume_nimbus.pdf"
    assert "base resume" in apps[0]["tailor_note"].lower()
    assert "Acme" in apps[0]["email_why"]
    assert "Nimbus" in apps[1]["email_why"]
    for app in apps:
        pdf = home / ".ribhus" / "job_hunt" / "apps" / app["id"] / app["pdf_file"]
        assert pdf.read_bytes() == b"%PDF-batch"

    dropped = client.put(
        f"/api/jobs/batches/{body['id']}",
        headers=headers,
        json={
            "items": [
                {
                    "id": apps[0]["id"],
                    "kept": False,
                    "to": apps[0]["to"],
                    "subject": apps[0]["subject"],
                    "body": apps[0]["body"],
                },
                {
                    "id": apps[1]["id"],
                    "kept": True,
                    "to": "hello@nimbus.test",
                    "subject": "Hello Nimbus",
                    "body": apps[1]["body"],
                },
            ]
        },
    )
    assert dropped.status_code == 200, dropped.text
    saved = dropped.json()["applications"]
    assert saved[0]["kept"] is False
    assert saved[1]["to"] == "hello@nimbus.test"


def test_send_next_sends_kept_drafts_one_at_a_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    service = JobHuntService(tmp_path / "job_hunt")
    service.save_resume(BASE_TEX)
    batch = service.store.create_batch(
        {"status": "review", "note": "", "omitted": 0, "error": "", "application_ids": []}
    )
    ids: list[str] = []
    for recipient, kept in (
        ("", True),
        ("jobs@nimbus.test", True),
        ("drop@acme.test", False),
    ):
        record = service.store.create(
            {
                "batch_id": batch["id"],
                "kept": kept,
                "to": recipient,
                "subject": "Hello",
                "body": "Hello there",
                "pdf_file": "resume_base.pdf",
                "pdf_ready": True,
                "status": "ready",
                "error": "",
            }
        )
        folder = service.store.folder(record["id"])
        (folder / "resume_base.pdf").write_bytes(b"%PDF")
        ids.append(record["id"])
    service.store.update_batch(batch["id"], application_ids=ids)

    sent: list[str] = []

    class FakeSender:
        def __init__(self, _session: object) -> None:
            return None

        async def send_new(self, **kwargs: object) -> None:
            sent.append(str(kwargs["to"]))

    monkeypatch.setattr("ribhus.jobs.service.GmailSender", FakeSender)
    policy = EmailPolicy(enabled=True, cooldown_seconds=0, sends_per_minute=10, sends_per_hour=20)
    step = asyncio.run(
        service.send_next(batch["id"], session=object(), policy=policy)  # type: ignore[arg-type]
    )
    assert sent == ["jobs@nimbus.test"]
    assert step["finished"] is True
    assert step["sent_id"] == ids[1]
    assert service.store.get(ids[0])["status"] == "skipped"
    assert service.store.get(ids[2])["status"] == "ready"


def test_wait_for_send_sleeps_through_cooldown(monkeypatch: pytest.MonkeyPatch):
    policy = EmailPolicy(enabled=True, cooldown_seconds=8, sends_per_minute=3, sends_per_hour=15)
    policy.record_send("talent@acme.test", "Hello")
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        policy._sends.clear()

    monkeypatch.setattr("ribhus.jobs.service.asyncio.sleep", fake_sleep)
    asyncio.run(_wait_for_send(policy, "jobs@nimbus.test", "Hello", "Body"))
    assert slept and slept[0] >= 8


def test_send_next_stops_when_gmail_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    service = JobHuntService(tmp_path / "job_hunt")
    batch = service.store.create_batch(
        {"status": "review", "note": "", "omitted": 0, "error": "", "application_ids": []}
    )
    record = service.store.create(
        {
            "kept": True,
            "to": "talent@acme.test",
            "subject": "Hello",
            "body": "Hello there",
            "pdf_file": "resume_base.pdf",
            "pdf_ready": True,
            "status": "ready",
            "error": "",
        }
    )
    (service.store.folder(record["id"]) / "resume_base.pdf").write_bytes(b"%PDF")
    service.store.update_batch(batch["id"], application_ids=[record["id"]])

    class FakeSender:
        def __init__(self, _session: object) -> None:
            return None

        async def send_new(self, **_kwargs: object) -> None:
            raise RuntimeError("compose failed")

    monkeypatch.setattr("ribhus.jobs.service.GmailSender", FakeSender)
    policy = EmailPolicy(enabled=True, cooldown_seconds=0, sends_per_minute=10, sends_per_hour=20)
    step = asyncio.run(
        service.send_next(batch["id"], session=object(), policy=policy)  # type: ignore[arg-type]
    )
    assert step["stopped"] is True
    assert step["finished"] is False
    assert "compose failed" in step["batch"]["error"]
    assert service.store.get(record["id"])["status"] == "ready"
