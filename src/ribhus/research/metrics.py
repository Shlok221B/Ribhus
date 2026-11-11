"""Compute research quality metrics for a completed run."""

from __future__ import annotations

from ribhus.models.base import TokenUsage
from ribhus.research.models import (
    EvaluationResult,
    JobRecord,
    ResearchMetrics,
    ResearchPlan,
    SearchLead,
)
from ribhus.research.quality import constraint_satisfaction_score


def compute_metrics(
    *,
    records: list[JobRecord],
    leads: list[SearchLead],
    evaluation: EvaluationResult | None,
    usage: TokenUsage,
    elapsed_seconds: float,
    iterations: int,
    queries_run: int,
    urls_investigated: int,
    raw_record_count: int,
    plan: ResearchPlan | None = None,
) -> ResearchMetrics:
    open_records = [r for r in records if r.status != "closed"]
    with_apply = [r for r in open_records if r.application_url]
    apply_ok = [
        r for r in open_records if r.verification.application_page_accessible
    ]
    active = [r for r in open_records if r.verification.active_status_confirmed]
    accessible = [r for r in open_records if r.verification.job_page_accessible]

    n = max(len(open_records), 1)
    dup_rate = None
    if raw_record_count > 0:
        dup_rate = max(0.0, 1.0 - (len(records) / raw_record_count))

    high_score_leads = [lead for lead in leads if lead.score >= 0.5]
    search_relevance = (
        len(high_score_leads) / len(leads) if leads else None
    )

    return ResearchMetrics(
        search_relevance=search_relevance,
        listing_precision=(len(accessible) / n) if open_records else 0.0,
        application_url_coverage=(len(with_apply) / n) if open_records else 0.0,
        application_page_accessibility=(len(apply_ok) / n) if open_records else 0.0,
        active_verification_rate=(len(active) / n) if open_records else 0.0,
        duplicate_rate=dup_rate,
        constraint_satisfaction=(
            constraint_satisfaction_score(open_records, plan) if plan else None
        ),
        research_completion_rate=(
            (evaluation.completion_score / 100.0) if evaluation else None
        ),
        average_research_cost_usd=usage.estimated_cost_usd,
        execution_time_seconds=elapsed_seconds,
        leads_discovered=len(leads),
        records_kept=len(open_records),
        urls_investigated=urls_investigated,
        iterations=iterations,
        queries_run=queries_run,
        total_tokens=usage.total_tokens,
    )
