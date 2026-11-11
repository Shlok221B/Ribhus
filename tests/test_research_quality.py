from ribhus.research.models import JobRecord, JobVerification, ResearchPlan
from ribhus.research.quality import filter_job_records, is_junk_record


def test_junk_titles_and_404():
    assert is_junk_record(
        JobRecord(role="Not found – 404 error", job_url="https://x.test/1")
    )
    assert is_junk_record(
        JobRecord(role="Job Board - Ashby Knowledge Base", job_url="https://ashbyhq.com/docs/x")
    )


def test_closed_listing_is_not_junk():
    closed = JobRecord(
        company="Zeta",
        role="Python Backend Developer",
        job_url="https://boards.greenhouse.io/zeta/jobs/1",
        status="closed",
        verification=JobVerification(closed_evidence="position closed"),
    )
    assert not is_junk_record(closed)


def test_filters_non_india_when_constraint_is_india():
    plan = ResearchPlan(
        objective="Python backend jobs in Pune or remote India",
        constraints={"location": "Pune or remote India", "role": "Python Backend"},
        domain="jobs",
    )
    canada = JobRecord(
        company="Wissen",
        role="Python Backend Engineer",
        location="Montreal, QC, Canada",
        job_url="https://jobs.example.com/1",
        status="accessible",
        verification=JobVerification(job_page_accessible=True),
    )
    pune = JobRecord(
        company="Hitachi",
        role="Python Backend Engineer",
        location="Pune, India",
        job_url="https://jobs.example.com/2",
        application_url="https://jobs.example.com/2/apply",
        status="application_url_found",
        verification=JobVerification(
            job_page_accessible=True, application_link_found=True
        ),
    )
    kept = filter_job_records([canada, pune], plan)
    assert len(kept) == 1
    assert kept[0].company == "Hitachi"
