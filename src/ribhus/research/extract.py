"""Structured extraction — deterministic first, LLM only to fill gaps."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from ribhus.models.router import ModelRouter
from ribhus.research.inspect.http_extract import PageSnapshot
from ribhus.research.models import JobRecord, JobVerification
from ribhus.research.status import apply_derived_status

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
        "explicit_fields": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": ["string", "null"]},
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
        "explicit_fields",
        "notes",
    ],
}

_EXPERIENCE_RE = re.compile(
    r"(\d+\s*[–\-to]{1,3}\s*\d+\s*\+?\s*years?|"
    r"\d+\+\s*years?|"
    r"minimum\s+of\s+\d+\s*years?|"
    r"at\s+least\s+\d+\s*years?)",
    re.IGNORECASE,
)

_SALARY_RE = re.compile(
    r"((?:₹|INR|Rs\.?|USD|\$|€)\s?[\d,]+(?:\s?[-–]\s?(?:₹|INR|Rs\.?|USD|\$|€)?\s?[\d,]+)?(?:\s*(?:LPA|lakh|pa|per\s+year|/yr|/year))?)",
    re.IGNORECASE,
)


def extract_job_from_snapshot(snap: PageSnapshot) -> JobRecord | None:
    """Deterministic extract from JSON-LD JobPosting + meta + apply links."""
    if snap.robots_allowed is False:
        return None
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
    explicit: list[str] = []
    field_sources: dict[str, str] = {}

    if posting:
        role = _str_or_none(posting.get("title"))
        if role:
            explicit.append("role")
            field_sources["role"] = "json_ld"
        org = posting.get("hiringOrganization")
        if isinstance(org, dict):
            company = _str_or_none(org.get("name"))
        elif isinstance(org, str):
            company = org
        if company:
            explicit.append("company")
            field_sources["company"] = "json_ld"
        loc = posting.get("jobLocation")
        location = _location_from_ld(loc)
        if location:
            explicit.append("location")
            field_sources["location"] = "json_ld"
        employment_type = _str_or_none(posting.get("employmentType"))
        if isinstance(employment_type, str) and employment_type.startswith("["):
            employment_type = employment_type.strip("[]\"' ")
        if employment_type:
            explicit.append("employment_type")
            field_sources["employment_type"] = "json_ld"
        date_posted = _str_or_none(posting.get("datePosted"))
        if date_posted:
            explicit.append("date_posted")
            field_sources["date_posted"] = "json_ld"
        valid_through = _str_or_none(posting.get("validThrough"))
        if valid_through:
            explicit.append("valid_through")
            field_sources["valid_through"] = "json_ld"
        application_url = _str_or_none(posting.get("url"))
        # directApply is often boolean — ignore non-URLs
        if application_url and not application_url.startswith("http"):
            application_url = None
        exp = posting.get("experienceRequirements")
        if isinstance(exp, str):
            experience = exp
        elif isinstance(exp, dict):
            experience = _str_or_none(
                exp.get("monthsOfExperience") or exp.get("description")
            )
        if experience:
            explicit.append("experience")
            field_sources["experience"] = "json_ld"
        skills = _skills_from_ld(posting)
        if skills:
            explicit.append("skills")
            field_sources["skills"] = "json_ld"
        salary = _salary_from_ld(posting.get("baseSalary"))
        if salary:
            explicit.append("salary")
            field_sources["salary"] = "json_ld"

    # Meta fallbacks
    if not role:
        role = _str_or_none(snap.meta.get("og:title") or snap.meta.get("twitter:title"))
        if role and not _looks_like_portal_home(snap.final_url, role):
            inferred.append("role")
            field_sources["role"] = "meta"
        else:
            role = None
    if not company:
        company = _str_or_none(
            snap.meta.get("og:site_name") or snap.meta.get("application-name")
        )
        if company and not _generic_site_name(company):
            inferred.append("company")
            field_sources["company"] = "meta"
        else:
            company = None

    if not company:
        company = _company_from_host(snap.final_url or snap.url)
        if company:
            inferred.append("company")
            field_sources["company"] = "host"

    apply_links = [link["url"] for link in snap.links if link.get("kind") == "apply"]
    if not application_url and apply_links:
        application_url = apply_links[0]
        explicit.append("application_url")
        field_sources["application_url"] = "anchor"
    elif application_url:
        explicit.append("application_url")
        field_sources["application_url"] = field_sources.get(
            "application_url", "json_ld"
        )

    if not role and snap.title:
        title = snap.title.strip()
        if 3 < len(title) < 120 and not _looks_like_portal_home(snap.final_url, title):
            role = _clean_title(title)
            if "role" not in inferred and "role" not in explicit:
                inferred.append("role")
                field_sources["role"] = "title"

    text = snap.text or ""
    if not experience:
        match = _EXPERIENCE_RE.search(text)
        if match:
            experience = match.group(1).strip()
            inferred.append("experience")
            field_sources["experience"] = "regex"
    if not salary:
        match = _SALARY_RE.search(text)
        if match:
            salary = match.group(1).strip()
            inferred.append("salary")
            field_sources["salary"] = "regex"
    if not location:
        location = _location_hint_from_text(text)
        if location:
            inferred.append("location")
            field_sources["location"] = "regex"

    if not role and not company and not snap.job_postings:
        if len(text.strip()) < 200:
            return None

    verification = JobVerification(
        job_page_accessible=bool(
            snap.status_code and 200 <= snap.status_code < 400 and not snap.error
        ),
        application_link_found=bool(application_url),
        closed_evidence=snap.closed_match,
        redirect_final_url=snap.final_url if snap.final_url != snap.url else None,
        http_status=snap.status_code or None,
        evidence_excerpt=text[:600] or None,
        redirect_chain=list(snap.redirect_chain or []),
    )

    record = JobRecord(
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
        verification=verification,
        inferred_fields=_uniq(inferred),
        explicit_fields=_uniq(explicit),
        field_sources=field_sources,
    )
    return apply_derived_status(record)


async def extract_job_with_llm(
    router: ModelRouter,
    snap: PageSnapshot,
) -> JobRecord | None:
    base = extract_job_from_snapshot(snap)
    # Strong deterministic hit — skip LLM
    if (
        base
        and base.company
        and base.role
        and (base.application_url or base.job_url)
        and "json_ld" in (base.field_sources.get("role"), base.field_sources.get("company"))
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
                    "Put clearly stated fields in explicit_fields; "
                    "uncertain guesses in inferred_fields. "
                    "application_url must be a real http(s) URL or null. "
                    "JSON only."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"URL: {snap.final_url or snap.url}\n"
                    f"Title: {snap.title}\n"
                    f"JSON-LD job postings: {snap.job_postings[:2]}\n"
                    f"Apply-ish links: "
                    f"{[l for l in snap.links if l.get('kind')=='apply'][:5]}\n\n"
                    f"Page text:\n{excerpt}"
                ),
            },
        ],
        json_schema=_EXTRACT_SCHEMA,
        max_tokens=900,
    )
    if not data:
        return base

    llm_apply = _null_str(data.get("application_url"))
    if llm_apply and not llm_apply.startswith("http"):
        llm_apply = None

    record = JobRecord(
        company=_null_str(data.get("company")),
        role=_null_str(data.get("role")),
        location=_null_str(data.get("location")),
        experience=_null_str(data.get("experience")),
        salary=_null_str(data.get("salary")),
        skills=[str(s) for s in (data.get("skills") or []) if s][:20],
        job_url=_null_str(data.get("job_url")) or (snap.final_url or snap.url),
        application_url=llm_apply,
        source_url=snap.url,
        date_posted=_null_str(data.get("date_posted")),
        valid_through=_null_str(data.get("valid_through")),
        employment_type=_null_str(data.get("employment_type")),
        notes=_null_str(data.get("notes")),
        inferred_fields=[str(x) for x in (data.get("inferred_fields") or []) if x],
        explicit_fields=[str(x) for x in (data.get("explicit_fields") or []) if x],
        verification=JobVerification(
            job_page_accessible=bool(
                snap.status_code and 200 <= snap.status_code < 400
            ),
            application_link_found=bool(llm_apply),
            closed_evidence=snap.closed_match,
            redirect_final_url=snap.final_url if snap.final_url != snap.url else None,
            http_status=snap.status_code or None,
            evidence_excerpt=(snap.text or "")[:600] or None,
            redirect_chain=list(snap.redirect_chain or []),
        ),
        field_sources={
            k: "llm"
            for k in (
                "company",
                "role",
                "location",
                "experience",
                "salary",
                "application_url",
            )
            if _null_str(data.get(k if k != "application_url" else "application_url"))
        },
    )

    # Prefer deterministic non-null over LLM
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
            "job_url",
        ):
            base_val = getattr(base, field_name)
            if base_val and not getattr(record, field_name):
                setattr(record, field_name, base_val)
                if field_name in base.field_sources:
                    record.field_sources[field_name] = base.field_sources[field_name]
            elif base_val and field_name in base.explicit_fields:
                # Prefer explicit deterministic over LLM
                setattr(record, field_name, base_val)
                record.field_sources[field_name] = base.field_sources.get(
                    field_name, "deterministic"
                )
        if base.skills and not record.skills:
            record.skills = base.skills
        record.explicit_fields = _uniq([*base.explicit_fields, *record.explicit_fields])
        record.inferred_fields = [
            f
            for f in _uniq([*base.inferred_fields, *record.inferred_fields])
            if f not in record.explicit_fields
        ]
        if base.verification.closed_evidence:
            record.verification.closed_evidence = base.verification.closed_evidence

    if not record.role and not record.company:
        return base
    return apply_derived_status(record)


def extract_general_finding(snap: PageSnapshot) -> JobRecord | None:
    """Lightweight structured finding for non-job deep research."""
    if snap.robots_allowed is False:
        return None
    if snap.error and not snap.text:
        return None
    title = (
        _str_or_none(snap.meta.get("og:title"))
        or _str_or_none(snap.title)
        or None
    )
    source = (
        _str_or_none(snap.meta.get("og:site_name"))
        or _company_from_host(snap.final_url or snap.url)
    )
    notes = (snap.text or "").strip()
    if notes:
        notes = notes[:500]
    if not title and not notes:
        return None
    record = JobRecord(
        company=source,
        role=title,
        job_url=snap.final_url or snap.url,
        source_url=snap.url,
        notes=notes,
        verification=JobVerification(
            job_page_accessible=bool(
                snap.status_code and 200 <= snap.status_code < 400 and not snap.error
            ),
            http_status=snap.status_code or None,
            evidence_excerpt=notes,
            redirect_chain=list(snap.redirect_chain or []),
            redirect_final_url=snap.final_url if snap.final_url != snap.url else None,
        ),
        explicit_fields=["role"] if title else [],
        field_sources={"role": "title", "company": "host"} if source else {"role": "title"},
    )
    return apply_derived_status(record)


def _uniq(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


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
    lower = title.lower()
    if path in {"", "/"} and any(
        w in lower for w in ("jobs", "indeed", "naukri", "linkedin", "careers")
    ):
        return True
    if any(
        w in lower
        for w in ("knowledge base", "help center", "page not found", "404")
    ):
        return True
    return False


def _generic_site_name(name: str) -> bool:
    lower = name.lower().strip()
    return lower in {
        "linkedin",
        "indeed",
        "naukri",
        "greenhouse",
        "lever",
        "ashby",
        "google",
        "twitter",
    }


def _company_from_host(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    # boards.greenhouse.io/acme → try path segment
    path = urlparse(url).path or ""
    if "greenhouse.io" in host or "lever.co" in host or "ashbyhq.com" in host:
        parts = [p for p in path.split("/") if p]
        if parts:
            slug = parts[0]
            if slug not in {"jobs", "job", "apply", "embed"}:
                return slug.replace("-", " ").title()
        return None
    if not host or host.count(".") < 1:
        return None
    root = host.split(".")[0]
    if root in {"www", "jobs", "careers", "boards", "apply"}:
        return None
    return root.replace("-", " ").title()


def _clean_title(title: str) -> str:
    # "Role - Company | Board" → Role
    text = title.strip()
    for sep in (" | ", " · ", " — ", " - "):
        if sep in text:
            text = text.split(sep)[0].strip()
            break
    return text[:160]


def _location_hint_from_text(text: str) -> str | None:
    patterns = [
        r"Location\s*[:\-]\s*([^\n|]{3,60})",
        r"Based in\s+([^\n|.]{3,60})",
        r"\b(Pune|Bengaluru|Bangalore|Hyderabad|Mumbai|Delhi|Noida|Gurugram|Remote(?:\s*[-,]?\s*India)?)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None
