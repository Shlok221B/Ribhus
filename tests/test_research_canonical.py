from ribhus.research.canonical import (
    canonicalize_url,
    lead_priority_score,
    query_fingerprint,
    record_fingerprint,
)
from ribhus.research.verify import dedupe_records
from ribhus.research.models import JobRecord


def test_canonicalize_strips_tracking_and_www():
    a = canonicalize_url(
        "https://www.Example.com/jobs/123/?utm_source=x&fbclid=1"
    )
    b = canonicalize_url("https://example.com/jobs/123")
    assert a == b


def test_query_fingerprint_normalizes_whitespace():
    assert query_fingerprint("Python  Backend") == query_fingerprint("python backend")


def test_record_fingerprint_prefers_company_role():
    assert record_fingerprint("Acme", "Backend Eng", "https://a") == record_fingerprint(
        "acme", "backend eng", "https://other"
    )


def test_ats_leads_score_higher_than_portal_home():
    ats = lead_priority_score(
        "https://boards.greenhouse.io/acme/jobs/1",
        "Backend Engineer",
        "Apply now",
    )
    portal = lead_priority_score("https://www.linkedin.com/jobs/", "Jobs", "Find jobs")
    assert ats > portal


def test_dedupe_keeps_stronger_status():
    weak = JobRecord(
        company="Acme",
        role="Backend",
        job_url="https://example.com/a",
        status="discovered",
    )
    strong = JobRecord(
        company="Acme",
        role="Backend",
        job_url="https://example.com/b",
        application_url="https://example.com/apply",
        status="active_confirmed",
    )
    out = dedupe_records([weak, strong])
    assert len(out) == 1
    assert out[0].status == "active_confirmed"
