from ribhus.research.extract import extract_general_finding, extract_job_from_snapshot
from ribhus.research.inspect.http_extract import parse_html
from ribhus.research.models import JobRecord, JobVerification, ResearchPlan
from ribhus.research.quality import filter_job_records, fits_role_constraints
from ribhus.research.status import derive_status
from ribhus.research.verify import _page_confirms, dedupe_records


def test_json_ld_extract_marks_explicit_fields():
    html = """
    <html><head><title>Ignore</title>
    <script type="application/ld+json">
    {
      "@type": "JobPosting",
      "title": "Python Backend Developer",
      "hiringOrganization": {"name": "Acme Labs"},
      "jobLocation": {"address": {"addressLocality": "Pune", "addressCountry": "IN"}},
      "url": "https://jobs.example.com/apply/1"
    }
    </script></head>
    <body><main><p>We need 3-5 years of experience with FastAPI.</p>
    <a href="/apply/1">Apply now</a></main></body></html>
    """
    snap = parse_html("https://jobs.example.com/1", "https://jobs.example.com/1", 200, html)
    record = extract_job_from_snapshot(snap)
    assert record is not None
    assert record.company == "Acme Labs"
    assert record.role == "Python Backend Developer"
    assert "company" in record.explicit_fields
    assert "role" in record.explicit_fields
    assert record.application_url
    assert record.status in {
        "application_url_found",
        "accessible",
        "discovered",
    }


def test_status_ladder_never_active_from_http_alone():
    record = JobRecord(
        company="Acme",
        role="Engineer",
        job_url="https://x.test/1",
        verification=JobVerification(job_page_accessible=True, http_status=200),
    )
    assert derive_status(record) == "accessible"
    record.application_url = "https://x.test/apply"
    record.verification.application_link_found = True
    assert derive_status(record) == "application_url_found"
    record.verification.application_page_accessible = True
    record.verification.active_status_confirmed = True
    assert derive_status(record) == "active_confirmed"
    record.verification.closed_evidence = "position closed"
    assert derive_status(record) == "closed"


def test_page_confirms_title_tokens():
    assert _page_confirms(
        "Python Backend Developer",
        "Acme is hiring a Python Backend Developer in Pune",
    )
    assert not _page_confirms("Python Backend Developer", "Welcome to our careers site")


def test_role_constraint_filters_dotnet():
    plan = ResearchPlan(
        objective="Python Backend Developer jobs in Pune",
        constraints={"role": "Python Backend Developer", "location": "Pune"},
        domain="jobs",
    )
    good = JobRecord(
        company="Hitachi",
        role="Python Backend Engineer",
        location="Pune, India",
        job_url="https://x.test/1",
        status="accessible",
        verification=JobVerification(job_page_accessible=True),
    )
    bad = JobRecord(
        company="VY",
        role=".NET Full Stack Developer (Angular / React)",
        location="Bengaluru",
        job_url="https://x.test/2",
        status="accessible",
        verification=JobVerification(job_page_accessible=True),
    )
    assert fits_role_constraints(good, plan)
    assert not fits_role_constraints(bad, plan)
    kept = filter_job_records([good, bad], plan)
    assert [r.company for r in kept] == ["Hitachi"]


def test_general_finding_extract():
    html = """
    <html><head><title>Zoho Corp overview</title>
    <meta property="og:site_name" content="Example News" />
    </head><body><main><p>Zoho is an Indian software company with products in CRM and office suite.</p>
    </main></body></html>
    """
    snap = parse_html("https://news.example.com/zoho", "https://news.example.com/zoho", 200, html)
    # Give it enough text
    snap.text = "Zoho is an Indian software company with products in CRM and office suite. " * 3
    finding = extract_general_finding(snap)
    assert finding is not None
    assert finding.role or finding.notes
    assert finding.verification.job_page_accessible


def test_dedupe_prefers_confirmed():
    weak = JobRecord(
        company="Acme",
        role="Backend",
        job_url="https://a.test/1",
        status="discovered",
    )
    strong = JobRecord(
        company="Acme",
        role="Backend",
        job_url="https://a.test/2",
        application_url="https://a.test/apply",
        status="active_confirmed",
        verification=JobVerification(
            application_link_found=True,
            application_page_accessible=True,
            active_status_confirmed=True,
            title_confirmed=True,
        ),
        explicit_fields=["role", "company"],
    )
    out = dedupe_records([weak, strong])
    assert len(out) == 1
    assert out[0].status == "active_confirmed"
