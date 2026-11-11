"""Verify research findings beyond HTTP 200."""

from __future__ import annotations

import asyncio
import re

from ribhus.research.canonical import canonicalize_url, record_fingerprint
from ribhus.research.inspect.http_extract import fetch_page
from ribhus.research.models import JobRecord, JobVerification
from ribhus.research.status import STATUS_RANK, apply_derived_status


def _normalize_token(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _page_confirms(needle: str | None, haystack: str) -> bool:
    if not needle:
        return False
    n = _normalize_token(needle)
    h = _normalize_token(haystack)
    if not n or len(n) < 3:
        return False
    if n in h:
        return True
    # Token overlap for multi-word titles
    tokens = [t for t in n.split() if len(t) > 2]
    if len(tokens) >= 2:
        hits = sum(1 for t in tokens if t in h)
        return hits >= max(2, (len(tokens) + 1) // 2)
    return False


async def verify_job_record(
    record: JobRecord,
    *,
    respect_robots: bool = True,
    retries: int = 2,
) -> JobRecord:
    """Probe listing + application URLs; confirm title/company; update status."""
    job_url = (record.job_url or record.source_url or "").strip()
    verification = record.verification.model_copy(deep=True)

    if job_url:
        snap = await fetch_page(
            job_url, respect_robots=respect_robots, retries=retries
        )
        verification.http_status = snap.status_code or None
        verification.redirect_chain = list(snap.redirect_chain or [])
        verification.job_page_accessible = bool(
            snap.robots_allowed
            and snap.status_code
            and 200 <= snap.status_code < 400
            and not snap.error
        )
        if snap.final_url and snap.final_url != job_url:
            verification.redirect_final_url = snap.final_url
            # Keep canonical job_url as final when redirected to a listing
            record.job_url = snap.final_url

        page_text = f"{snap.title}\n{snap.text}"
        verification.title_confirmed = _page_confirms(record.role, page_text)
        verification.company_confirmed = _page_confirms(record.company, page_text)
        verification.evidence_excerpt = (snap.text or "")[:600] or verification.evidence_excerpt

        if snap.closed_match:
            verification.closed_evidence = snap.closed_match
            verification.active_status_confirmed = False
        elif verification.job_page_accessible and snap.text:
            if not record.application_url:
                apply_links = [
                    link["url"] for link in snap.links if link.get("kind") == "apply"
                ]
                if apply_links:
                    record.application_url = apply_links[0]
            # Backfill missing fields from JSON-LD on verify pass
            if snap.job_postings:
                posting = snap.job_postings[0]
                if not record.role and posting.get("title"):
                    record.role = str(posting["title"]).strip()
                    verification.title_confirmed = _page_confirms(
                        record.role, page_text
                    )
                org = posting.get("hiringOrganization")
                if not record.company:
                    if isinstance(org, dict) and org.get("name"):
                        record.company = str(org["name"]).strip()
                    elif isinstance(org, str):
                        record.company = org.strip()
                    if record.company:
                        verification.company_confirmed = _page_confirms(
                            record.company, page_text
                        )

    if record.application_url:
        verification.application_link_found = True
        # Same URL as listing — don't double-fetch unless needed
        same = canonicalize_url(record.application_url) == canonicalize_url(
            record.job_url or ""
        )
        if same and verification.job_page_accessible and not verification.closed_evidence:
            verification.application_page_accessible = True
        else:
            app_snap = await fetch_page(
                record.application_url,
                respect_robots=respect_robots,
                retries=retries,
            )
            app_ok = bool(
                app_snap.robots_allowed
                and app_snap.status_code
                and 200 <= app_snap.status_code < 400
                and not app_snap.error
                and not app_snap.closed_match
            )
            verification.application_page_accessible = app_ok
            if app_snap.closed_match:
                verification.closed_evidence = app_snap.closed_match
                verification.active_status_confirmed = False
            if app_snap.final_url:
                verification.redirect_final_url = app_snap.final_url
            if app_snap.status_code and verification.http_status is None:
                verification.http_status = app_snap.status_code

        # Active only with apply page OK + no closed evidence + some identity signal
        if (
            verification.application_page_accessible
            and not verification.closed_evidence
            and (
                verification.title_confirmed
                or verification.company_confirmed
                or bool(record.role and record.company)
            )
        ):
            verification.active_status_confirmed = True
        else:
            verification.active_status_confirmed = False

    record.verification = verification
    return apply_derived_status(record)


async def verify_records(
    records: list[JobRecord],
    *,
    max_parallel: int = 4,
    respect_robots: bool = True,
    retries: int = 2,
) -> list[JobRecord]:
    if not records:
        return []
    sem = asyncio.Semaphore(max(1, max_parallel))

    async def _one(record: JobRecord) -> JobRecord:
        async with sem:
            try:
                return await verify_job_record(
                    record, respect_robots=respect_robots, retries=retries
                )
            except Exception:  # noqa: BLE001
                return apply_derived_status(record)

    return list(await asyncio.gather(*[_one(r) for r in records]))


def dedupe_records(records: list[JobRecord]) -> list[JobRecord]:
    """Prefer stronger verification when fingerprints collide."""
    best: dict[str, JobRecord] = {}
    order: list[str] = []
    for record in records:
        fp = record_fingerprint(record.company, record.role, record.job_url)
        canon = canonicalize_url(record.job_url or record.source_url or "")
        key = fp or canon
        if not key:
            continue
        existing = best.get(key)
        if existing is None:
            best[key] = record
            order.append(key)
            continue
        if STATUS_RANK.get(record.status, 0) > STATUS_RANK.get(existing.status, 0):
            best[key] = record
        elif STATUS_RANK.get(record.status, 0) == STATUS_RANK.get(existing.status, 0):
            # Prefer confirmed identity + application_url + more explicit fields
            score_new = (
                int(bool(record.application_url))
                + int(record.verification.title_confirmed)
                + int(record.verification.company_confirmed)
                + len(record.explicit_fields)
            )
            score_old = (
                int(bool(existing.application_url))
                + int(existing.verification.title_confirmed)
                + int(existing.verification.company_confirmed)
                + len(existing.explicit_fields)
            )
            if score_new > score_old:
                best[key] = record
    return [best[k] for k in order]


def verification_summary(records: list[JobRecord]) -> dict[str, int]:
    return {
        "total": len(records),
        "accessible": sum(1 for r in records if r.verification.job_page_accessible),
        "apply_link": sum(1 for r in records if r.verification.application_link_found),
        "apply_page": sum(
            1 for r in records if r.verification.application_page_accessible
        ),
        "active_confirmed": sum(
            1 for r in records if r.verification.active_status_confirmed
        ),
        "title_confirmed": sum(1 for r in records if r.verification.title_confirmed),
        "company_confirmed": sum(
            1 for r in records if r.verification.company_confirmed
        ),
        "closed": sum(1 for r in records if r.status == "closed"),
    }
