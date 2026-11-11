"""Verify job listings beyond HTTP 200."""

from __future__ import annotations

import httpx

from ribhus.research.canonical import canonicalize_url, record_fingerprint
from ribhus.research.inspect.http_extract import _CLOSED_RE, fetch_page
from ribhus.research.models import JobRecord, JobVerification


async def verify_job_record(record: JobRecord) -> JobRecord:
    """Probe job page and application URL; update verification + status."""
    job_url = (record.job_url or record.source_url or "").strip()
    verification = record.verification.model_copy(deep=True)

    if job_url:
        snap = await fetch_page(job_url)
        verification.http_status = snap.status_code or None
        verification.job_page_accessible = bool(
            snap.status_code and 200 <= snap.status_code < 400 and not snap.error
        )
        verification.redirect_final_url = (
            snap.final_url if snap.final_url and snap.final_url != job_url else None
        )
        if snap.closed_match:
            verification.closed_evidence = snap.closed_match
            verification.active_status_confirmed = False
            record.status = "closed"
        elif verification.job_page_accessible and snap.text:
            # Positive active signal only with explicit apply affordance + no closed text
            has_apply = bool(
                record.application_url
                or any(link.get("kind") == "apply" for link in snap.links)
                or "apply" in snap.text.lower()
            )
            if has_apply and not snap.closed_match:
                verification.active_status_confirmed = False  # still not confirmed open
            verification.evidence_excerpt = (snap.text or "")[:600] or None
            if not record.application_url:
                apply_links = [
                    link["url"] for link in snap.links if link.get("kind") == "apply"
                ]
                if apply_links:
                    record.application_url = apply_links[0]
                    verification.application_link_found = True

    if record.application_url:
        verification.application_link_found = True
        app_ok, app_status, app_closed, final = await _probe_application(
            record.application_url
        )
        verification.application_page_accessible = app_ok
        if app_status is not None and verification.http_status is None:
            verification.http_status = app_status
        if app_closed:
            verification.closed_evidence = app_closed
            record.status = "closed"
            verification.active_status_confirmed = False
        elif app_ok and record.status != "closed":
            record.status = "application_accessible"
            # Confirm active only if apply page OK and no closed evidence
            if not verification.closed_evidence:
                verification.active_status_confirmed = True
                record.status = "active_confirmed"
        if final:
            verification.redirect_final_url = final
    elif verification.job_page_accessible and record.status not in {
        "closed",
        "application_url_found",
        "application_accessible",
        "active_confirmed",
    }:
        record.status = "accessible"

    record.verification = verification
    return record


async def verify_records(records: list[JobRecord]) -> list[JobRecord]:
    out: list[JobRecord] = []
    for record in records:
        try:
            out.append(await verify_job_record(record))
        except Exception:  # noqa: BLE001
            out.append(record)
    return out


def dedupe_records(records: list[JobRecord]) -> list[JobRecord]:
    """Prefer stronger verification when fingerprints collide."""
    rank = {
        "active_confirmed": 6,
        "application_accessible": 5,
        "application_url_found": 4,
        "accessible": 3,
        "discovered": 2,
        "unknown": 1,
        "closed": 0,
    }
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
        if rank.get(record.status, 0) > rank.get(existing.status, 0):
            best[key] = record
        elif rank.get(record.status, 0) == rank.get(existing.status, 0):
            # Prefer one with application_url
            if record.application_url and not existing.application_url:
                best[key] = record
    return [best[k] for k in order]


async def _probe_application(
    url: str,
) -> tuple[bool, int | None, str | None, str | None]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; RibhusResearch/0.1; +https://github.com/ribhus)"
        ),
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }
    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=25.0, headers=headers
        ) as client:
            response = await client.get(url)
    except httpx.HTTPError:
        return False, None, None, None

    status = response.status_code
    ok = 200 <= status < 400
    text = (response.text or "")[:8000]
    closed = None
    match = _CLOSED_RE.search(text)
    if match:
        closed = match.group(0)
        ok = False
    return ok, status, closed, str(response.url)
