"""Canonical research record status ladder.

HTTP 200 alone never means active_confirmed.
"""

from __future__ import annotations

from typing import Literal

from ribhus.research.models import JobRecord, JobVerification

Status = Literal[
    "unknown",
    "discovered",
    "accessible",
    "application_url_found",
    "application_accessible",
    "active_confirmed",
    "closed",
]

STATUS_RANK: dict[str, int] = {
    "active_confirmed": 6,
    "application_accessible": 5,
    "application_url_found": 4,
    "accessible": 3,
    "discovered": 2,
    "unknown": 1,
    "closed": 0,
}


def derive_status(record: JobRecord) -> Status:
    """Compute status from verification signals — never invent active."""
    v = record.verification
    if v.closed_evidence or record.status == "closed":
        return "closed"
    if v.active_status_confirmed and v.application_page_accessible:
        return "active_confirmed"
    if v.application_page_accessible:
        return "application_accessible"
    if v.application_link_found or record.application_url:
        return "application_url_found"
    if v.job_page_accessible:
        return "accessible"
    if record.job_url or record.source_url:
        return "discovered"
    return "unknown"


def apply_derived_status(record: JobRecord) -> JobRecord:
    record.status = derive_status(record)
    return record


def merge_verification(
    base: JobVerification, update: JobVerification
) -> JobVerification:
    """Prefer True / non-null evidence from update when stronger."""
    return JobVerification(
        job_page_accessible=base.job_page_accessible or update.job_page_accessible,
        application_link_found=base.application_link_found
        or update.application_link_found,
        application_page_accessible=base.application_page_accessible
        or update.application_page_accessible,
        active_status_confirmed=update.active_status_confirmed
        if update.active_status_confirmed
        else base.active_status_confirmed and not update.closed_evidence,
        title_confirmed=base.title_confirmed or update.title_confirmed,
        company_confirmed=base.company_confirmed or update.company_confirmed,
        closed_evidence=update.closed_evidence or base.closed_evidence,
        redirect_final_url=update.redirect_final_url or base.redirect_final_url,
        http_status=update.http_status
        if update.http_status is not None
        else base.http_status,
        evidence_excerpt=update.evidence_excerpt or base.evidence_excerpt,
        redirect_chain=update.redirect_chain or base.redirect_chain,
    )
