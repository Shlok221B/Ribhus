"""Structured extraction — deterministic first, LLM fallback."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from ribhus.models.router import ModelRouter
from ribhus.research.inspect.http_extract import PageSnapshot
from ribhus.research.models import JobRecord, JobVerification

_EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "company": {"type": ["string", "null"]},
        "role": {"type": ["string", "null"]},
        "location": {"type": ["string", "null"]},
        "experience": {"type": ["string", "null"]},
        "salary": {"type": ["string", "null"]},
        "skills": {"type": "array", "items": {"type": "string"}},
        "job_url": {"type": ["string", "null"]},
        "application_url": {"type": ["string", "null"]},
        "date_posted": {"type": ["string", "null"]},
        "valid_through": {"type": ["string", "null"]},
        "employment_type": {"type": ["string", "null"]},
        "inferred_fields": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "company",
        "role",
        "location",
        "experience",
        "salary",
        "skills",
        "job_url",
        "application_url",
        "date_posted",
        "valid_through",
        "employment_type",
        "inferred_fields",
    ],
}


def extract_job_from_snapshot(snap: PageSnapshot) -> JobRecord | None:
    """Deterministic extract from JSON-LD JobPosting + apply links."""
    if snap.error and not snap.job_postings and not snap.text:
        return None

    posting = snap.job_postings[0] if snap.job_postings else None
    company = None
    role = None
    location = None
    experience = None
    salary = None
    skills: list[str] = []
    date_posted = None
    valid_through = None
    employment_type = None
    application_url = None
    inferred: list[str] = []

    if posting:
        role = _str_or_none(posting.get("title"))
        org = posting.get("hiringOrganization")
        if isinstance(org, dict):
            company = _str_or_none(org.get("name"))
        elif isinstance(org, str):
            company = org
        loc = posting.get("jobLocation")
        location = _location_from_ld(loc)
        employment_type = _str_or_none(posting.get("employmentType"))
        date_posted = _str_or_none(posting.get("datePosted"))
        valid_through = _str_or_none(posting.get("validThrough"))
        application_url = _str_or_none(
            posting.get("directApply") or posting.get("url")
        )
        if isinstance(posting.get("applicationContact"), dict):
            pass
        exp = posting.get("experienceRequirements")
        if isinstance(exp, str):
            experience = exp
        elif isinstance(exp, dict):
            experience = _str_or_none(exp.get("monthsOfExperience") or exp.get("description"))
        skills = _skills_from_ld(posting)
        sal = posting.get("baseSalary")
        salary = _salary_from_ld(sal)

    apply_links = [link["url"] for link in snap.links if link.get("kind") == "apply"]
    if not application_url and apply_links:
        application_url = apply_links[0]

    if not role and snap.title:
        # Only use title if it looks like a job title, not a board homepage
        title = snap.title.strip()
        if 3 < len(title) < 120 and not _looks_like_portal_home(snap.final_url, title):
            role = title
            inferred.append("role")

    if not company:
        host = urlparse(snap.final_url).hostname or ""
        if host and "greenhouse" not in host and "lever" not in host:
            inferred.append("company")

    if not role and not company and not snap.job_postings:
        # Not enough structured signal — caller may LLM-extract
        if len(snap.text.strip()) < 200:
            return None

    status = "discovered"
    if snap.status_code and snap.status_code < 400 and snap.text:
        status = "accessible"
    if application_url:
        status = "application_url_found"
    if snap.closed_match:
        status = "closed"

    verification = JobVerification(
        job_page_accessible=bool(snap.status_code and 200 <= snap.status_code < 400),
        application_link_found=bool(application_url),
        closed_evidence=snap.closed_match,
        redirect_final_url=snap.final_url if snap.final_url != snap.url else None,
        http_status=snap.status_code or None,
        evidence_excerpt=(snap.text or "")[:600] or None,
    )

    return JobRecord(
        company=company,
        role=role,
        location=location,
        experience=experience,
        salary=salary,
        skills=skills,
        job_url=snap.final_url or snap.url,
        application_url=application_url,
        source_url=snap.url,
        date_posted=date_posted,
        valid_through=valid_through,
        employment_type=employment_type,
        status=status,  # type: ignore[arg-type]
        verification=verification,
        inferred_fields=inferred,
    )


async def extract_job_with_llm(
    router: ModelRouter,
    snap: PageSnapshot,
) -> JobRecord | None:
    base = extract_job_from_snapshot(snap)
    # If JSON-LD already filled company+role+apply, skip LLM
    if (
        base
        and base.company
        and base.role
        and (base.application_url or base.job_url)
        and not base.inferred_fields
    ):
        return base

    if not snap.text and not snap.job_postings:
        return base

    excerpt = (snap.text or "")[:7000]
    data = await router.complete_json(
        "extract",
        [
            {
                "role": "system",
                "content": (
                    "Extract job listing fields from page text. "
                    "Never invent missing values — use null. "
                    "Mark fields you inferred (not explicit) in inferred_fields. "
                    "JSON only."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"URL: {snap.final_url or snap.url}\n"
                    f"Title: {snap.title}\n"
                    f"JSON-LD job postings: {snap.job_postings[:2]}\n"
                    f"Apply-ish links: {[l for l in snap.links if l.get('kind')=='apply'][:5]}\n\n"
                    f"Page text:\n{excerpt}"
                ),
            },
        ],
        json_schema=_EXTRACT_SCHEMA,
        max_tokens=900,
    )
    if not data:
        return base

    record = JobRecord(
        company=_null_str(data.get("company")),
        role=_null_str(data.get("role")),
        location=_null_str(data.get("location")),
        experience=_null_str(data.get("experience")),
        salary=_null_str(data.get("salary")),
        skills=[str(s) for s in (data.get("skills") or []) if s][:20],
        job_url=_null_str(data.get("job_url")) or (snap.final_url or snap.url),
        application_url=_null_str(data.get("application_url")),
        source_url=snap.url,
        date_posted=_null_str(data.get("date_posted")),
        valid_through=_null_str(data.get("valid_through")),
        employment_type=_null_str(data.get("employment_type")),
        inferred_fields=[str(x) for x in (data.get("inferred_fields") or []) if x],
        verification=JobVerification(
            job_page_accessible=bool(snap.status_code and 200 <= snap.status_code < 400),
            application_link_found=bool(_null_str(data.get("application_url"))),
            closed_evidence=snap.closed_match,
            redirect_final_url=snap.final_url if snap.final_url != snap.url else None,
            http_status=snap.status_code or None,
            evidence_excerpt=(snap.text or "")[:600] or None,
        ),
        status="closed"
        if snap.closed_match
        else (
            "application_url_found"
            if _null_str(data.get("application_url"))
            else "accessible"
            if snap.text
            else "discovered"
        ),
    )
    # Prefer non-null deterministic fields over LLM when both present
    if base:
        for field_name in (
            "company",
            "role",
            "location",
            "experience",
            "salary",
            "date_posted",
            "valid_through",
            "employment_type",
            "application_url",
        ):
            if getattr(base, field_name) and not getattr(record, field_name):
                setattr(record, field_name, getattr(base, field_name))
        if base.skills and not record.skills:
            record.skills = base.skills
    if not record.role and not record.company:
        return base
    return record


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _null_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a", "unknown"}:
        return None
    return text


def _location_from_ld(loc: Any) -> str | None:
    if isinstance(loc, str):
        return loc
    if isinstance(loc, list) and loc:
        return _location_from_ld(loc[0])
    if isinstance(loc, dict):
        if "address" in loc:
            return _location_from_ld(loc["address"])
        parts = [
            loc.get("addressLocality"),
            loc.get("addressRegion"),
            loc.get("addressCountry"),
        ]
        text = ", ".join(str(p) for p in parts if p)
        return text or _str_or_none(loc.get("name"))
    return None


def _skills_from_ld(posting: dict[str, Any]) -> list[str]:
    skills: list[str] = []
    for key in ("skills", "qualifications", "knowledge"):
        val = posting.get(key)
        if isinstance(val, str):
            skills.extend(re.split(r"[,;|/]", val))
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, str):
                    skills.append(item)
                elif isinstance(item, dict) and item.get("name"):
                    skills.append(str(item["name"]))
    return [s.strip() for s in skills if s and str(s).strip()][:20]


def _salary_from_ld(sal: Any) -> str | None:
    if isinstance(sal, str):
        return sal
    if not isinstance(sal, dict):
        return None
    value = sal.get("value")
    currency = sal.get("currency") or ""
    if isinstance(value, dict):
        minimum = value.get("minValue") or value.get("value")
        maximum = value.get("maxValue")
        unit = value.get("unitText") or ""
        if minimum and maximum:
            return f"{currency} {minimum}-{maximum} {unit}".strip()
        if minimum:
            return f"{currency} {minimum} {unit}".strip()
    if value is not None:
        return f"{currency} {value}".strip()
    return None


def _looks_like_portal_home(url: str, title: str) -> bool:
    path = urlparse(url).path or "/"
    if path in {"", "/"} and any(
        w in title.lower() for w in ("jobs", "indeed", "naukri", "linkedin", "careers")
    ):
        return True
    return False
