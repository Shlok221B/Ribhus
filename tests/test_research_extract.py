from ribhus.research.extract import extract_job_from_snapshot
from ribhus.research.inspect.http_extract import parse_html


def test_extract_jobposting_json_ld():
    html = """
    <html><head><title>Ignore</title>
    <script type="application/ld+json">
    {
      "@type": "JobPosting",
      "title": "Python Backend Developer",
      "hiringOrganization": {"@type": "Organization", "name": "Ribhus Labs"},
      "jobLocation": {
        "@type": "Place",
        "address": {
          "@type": "PostalAddress",
          "addressLocality": "Pune",
          "addressCountry": "IN"
        }
      },
      "datePosted": "2026-11-01",
      "url": "https://jobs.example.com/apply/1"
    }
    </script>
    </head><body>
    <main><h1>Python Backend Developer</h1>
    <a href="/apply/1">Apply now</a>
    <p>We are hiring a Python backend developer in Pune with FastAPI.</p>
    </main></body></html>
    """
    snap = parse_html(
        "https://jobs.example.com/1",
        "https://jobs.example.com/1",
        200,
        html,
    )
    assert snap.job_postings
    record = extract_job_from_snapshot(snap)
    assert record is not None
    assert record.role == "Python Backend Developer"
    assert record.company == "Ribhus Labs"
    assert record.location and "Pune" in record.location
    assert record.application_url or record.job_url


def test_closed_position_detected():
    html = """
    <html><body><main>
    <h1>Backend Engineer</h1>
    <p>This position has been closed and is no longer accepting applications.</p>
    </main></body></html>
    """
    snap = parse_html("https://x.test/job", "https://x.test/job", 200, html)
    assert snap.closed_match
    record = extract_job_from_snapshot(snap)
    assert record is not None
    assert record.status == "closed"
