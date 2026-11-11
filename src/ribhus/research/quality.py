"""Filter and score job records for relevance / quality."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from ribhus.research.models import JobRecord, ResearchPlan

_JUNK_TITLE_RE = re.compile(
    r"(?i)^("
    r"not\s+found|404|error|page\s+not\s+found|"
    r"job\s+board|knowledge\s+base|help\s+center|"
    r"sign\s+in|log\s+in|login|cookie|"
    r"lever\s+hire|indeed|naukri|linkedin\s+jobs?"
    r")\b"
)

_JUNK_HOST_PATH = (
    "ashbyhq.com/docs",
    "ashbyhq.com/knowledge",
    "support.lever.co",
    "help.greenhouse.io",
    "support.linkedin.com",
)

_INDIA_MARKERS = (
    "india",
    "pune",
    "bengaluru",
    "bangalore",
    "hyderabad",
    "mumbai",
    "delhi",
    "chennai",
    "noida",
    "gurgaon",
    "gurugram",
    "remote india",
    "in-remote",
    ", in",
    " maharashtra",
    " karnataka",
)

_NON_INDIA_MARKERS = (
    "montreal",
    "canada",
    "united states",
    "usa",
    " u.s.",
    "california",
    "new york",
    "london",
    "uk,",
    "united kingdom",
    "germany",
    "berlin",
    "australia",
    "singapore",  # often wrong for "India" asks unless user said so
)


def is_junk_record(record: JobRecord) -> bool:
    title = (record.role or "").strip()
    company = (record.company or "").strip()
    if _JUNK_TITLE_RE.search(title):
        return True
    if title.lower() in {"", "jobs", "careers", "home"}:
        return True
    url_blob = " ".join(
        filter(None, [record.job_url, record.application_url, record.source_url])
    ).lower()
    if any(j in url_blob for j in _JUNK_HOST_PATH):
        return True
    if record.status == "closed":
        return True
    if record.verification.http_status and record.verification.http_status >= 400:
        return True
    # No identity at all
    if not company and not title:
        return True
    if not (record.job_url or record.application_url or record.source_url):
        return True
    return False


def fits_location_constraints(record: JobRecord, plan: ResearchPlan) -> bool:
    constraints = plan.constraints or {}
    loc_want = " ".join(
        str(constraints.get(k) or "")
        for k in ("location", "remote", "city")
    ).lower()
    objective = (plan.objective or "").lower()
    want_india = any(
        m in loc_want or m in objective
        for m in ("india", "pune", "bengaluru", "bangalore", "hyderabad", "mumbai")
    )
    want_remote = "remote" in loc_want or "remote" in objective
    blob = " ".join(
        filter(
            None,
            [record.location, record.role, record.company, record.job_url, record.notes],
        )
    ).lower()

    if not want_india:
        return True

    if any(m in blob for m in _NON_INDIA_MARKERS) and not any(
        m in blob for m in _INDIA_MARKERS
    ):
        # Allow pure remote if user asked remote India and location says remote only
        if want_remote and re.search(r"\bremote\b", blob) and not any(
            m in blob for m in _NON_INDIA_MARKERS
        ):
            return True
        return False
    return True


def filter_job_records(
    records: list[JobRecord], plan: ResearchPlan
) -> list[JobRecord]:
    kept: list[JobRecord] = []
    for record in records:
        if is_junk_record(record):
            continue
        if plan.domain == "jobs" and not fits_location_constraints(record, plan):
            continue
        kept.append(record)
    return kept


def opening_payload(record: JobRecord) -> dict:
    apply = record.application_url or record.job_url or record.source_url
    listing = record.job_url or record.source_url
    host = ""
    try:
        host = (urlparse(apply or listing or "").hostname or "").removeprefix("www.")
    except Exception:  # noqa: BLE001
        host = ""
    return {
        "company": record.company,
        "role": record.role,
        "location": record.location,
        "experience": record.experience,
        "salary": record.salary,
        "skills": record.skills[:8],
        "job_url": listing,
        "application_url": record.application_url or apply,
        "date_posted": record.date_posted,
        "status": record.status,
        "verification": {
            "job_page_accessible": record.verification.job_page_accessible,
            "application_link_found": record.verification.application_link_found,
            "application_page_accessible": record.verification.application_page_accessible,
            "active_status_confirmed": record.verification.active_status_confirmed,
        },
        "host": host,
        "relevance_score": record.relevance_score,
    }
