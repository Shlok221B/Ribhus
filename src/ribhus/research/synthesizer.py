"""Final research synthesis for the user."""

from __future__ import annotations

import json

from ribhus.models.router import ModelRouter
from ribhus.research.models import (
    EvaluationResult,
    JobRecord,
    ResearchMetrics,
    ResearchPlan,
    ResearchResult,
)
from ribhus.research.quality import filter_job_records, opening_payload

_STATUS_RANK = {
    "active_confirmed": 0,
    "application_accessible": 1,
    "application_url_found": 2,
    "accessible": 3,
    "discovered": 4,
    "unknown": 5,
    "closed": 6,
}


async def synthesize_results(
    router: ModelRouter,
    *,
    user_objective: str,
    plan: ResearchPlan,
    records: list[JobRecord],
    evaluation: EvaluationResult | None,
    metrics: ResearchMetrics,
    incomplete: bool,
) -> ResearchResult:
    ranked = _rank_records(filter_job_records(records, plan), plan)
    if plan.domain == "jobs":
        # Deterministic markdown + structured fence for the UI.
        # Do not LLM-polish job rows — models strip/rewrite URLs into "Apply Here".
        summary = _jobs_markdown(
            user_objective, plan, ranked, evaluation, metrics, incomplete
        )
        summary = summary + "\n\n" + _jobs_data_fence(user_objective, plan, ranked, metrics, incomplete)
    else:
        summary = await _general_markdown(
            router, user_objective, plan, ranked, evaluation, metrics, incomplete
        )

    limitations: list[str] = []
    if incomplete:
        limitations.append("Research stopped before the evaluator marked full completion.")
    if evaluation and evaluation.missing_information:
        limitations.extend(evaluation.missing_information)
    if plan.domain == "jobs" and len([r for r in ranked if r.status != "closed"]) < 5:
        limitations.append("Fewer than 5 verified openings survived filtering.")

    return ResearchResult(
        objective=user_objective,
        plan=plan,
        records=ranked,
        evaluation=evaluation,
        metrics=metrics,
        summary_markdown=summary,
        limitations=limitations,
        incomplete=incomplete,
    )


def _rank_records(records: list[JobRecord], plan: ResearchPlan) -> list[JobRecord]:
    constraints = plan.constraints or {}
    location = str(constraints.get("location") or "").lower()
    role = str(constraints.get("role") or "").lower()

    def score(record: JobRecord) -> tuple:
        rel = 0.0
        blob = " ".join(
            filter(
                None,
                [
                    record.role,
                    record.company,
                    record.location,
                    record.experience,
                    " ".join(record.skills),
                ],
            )
        ).lower()
        if role and role in blob:
            rel += 2
        if location and any(part in blob for part in location.replace(",", " ").split() if len(part) > 2):
            rel += 2
        if record.application_url:
            rel += 1.5
        if record.verification.application_page_accessible:
            rel += 1
        if record.verification.active_status_confirmed:
            rel += 1
        if record.company:
            rel += 0.5
        record.relevance_score = rel
        return (_STATUS_RANK.get(record.status, 9), -rel)

    return sorted(records, key=score)


def _jobs_data_fence(
    user_objective: str,
    plan: ResearchPlan,
    records: list[JobRecord],
    metrics: ResearchMetrics,
    incomplete: bool,
) -> str:
    constraints = plan.constraints or {}
    kept = [r for r in records if r.status != "closed"]
    payload = {
        "type": "ribhus_jobs",
        "objective": user_objective,
        "ask": {
            "role": constraints.get("role") or None,
            "location": constraints.get("location")
            or constraints.get("remote")
            or None,
            "experience": constraints.get("experience")
            or constraints.get("seniority")
            or None,
        },
        "summary": {
            "listings": len(kept),
            "with_apply": sum(1 for r in kept if r.application_url),
            "apply_accessible": sum(
                1 for r in kept if r.verification.application_page_accessible
            ),
            "active_confirmed": sum(
                1 for r in kept if r.verification.active_status_confirmed
            ),
            "iterations": metrics.iterations,
            "urls_investigated": metrics.urls_investigated,
            "incomplete": incomplete,
        },
        "openings": [opening_payload(r) for r in kept[:20]],
    }
    return "```ribhus-jobs\n" + json.dumps(payload, indent=2) + "\n```"


def _jobs_markdown(
    user_objective: str,
    plan: ResearchPlan,
    records: list[JobRecord],
    evaluation: EvaluationResult | None,
    metrics: ResearchMetrics,
    incomplete: bool,
) -> str:
    constraints = plan.constraints or {}
    lines = [
        f"# Job search: {constraints.get('role') or 'Openings'}",
        "",
        "## Ask",
        f"- Role: {constraints.get('role') or '(see objective)'}",
        f"- Location / remote: {constraints.get('location') or constraints.get('remote') or '(see objective)'}",
        f"- Seniority / experience: {constraints.get('experience') or constraints.get('seniority') or '(see objective)'}",
        f"- Objective: {user_objective}",
        "",
        "## Openings",
    ]
    kept = [r for r in records if r.status != "closed" and (r.role or r.company)]
    if not kept:
        lines.append("_No verified individual openings extracted yet._")
    for i, record in enumerate(kept[:15], start=1):
        title = record.role or "(role unknown)"
        company = record.company or "(company unknown)"
        loc = record.location or "n/a"
        lines.append(f"{i}. **{title}** — {company} — {loc}")
        why_bits = []
        if record.experience:
            why_bits.append(f"experience: {record.experience}")
        if record.skills:
            why_bits.append("skills: " + ", ".join(record.skills[:6]))
        if record.salary:
            why_bits.append(f"salary: {record.salary}")
        if why_bits:
            lines.append(f"   Why: {'; '.join(why_bits)}")
        apply = record.application_url or record.job_url or record.source_url
        if apply:
            lines.append(f"   Apply: {apply}")
        if (
            record.job_url
            and record.application_url
            and record.job_url != record.application_url
        ):
            lines.append(f"   Listing: {record.job_url}")
        if record.date_posted:
            lines.append(f"   Posted: {record.date_posted}")
        lines.append(
            "   Verification: "
            f"page={'yes' if record.verification.job_page_accessible else 'no'}, "
            f"apply_link={'yes' if record.verification.application_link_found else 'no'}, "
            f"apply_page={'yes' if record.verification.application_page_accessible else 'no'}, "
            f"active={'yes' if record.verification.active_status_confirmed else 'unconfirmed'}, "
            f"status={record.status}"
        )
        lines.append("")

    closed = [r for r in records if r.status == "closed"]
    lines.extend(
        [
            "## Research summary",
            f"- Listings kept: {len(kept)}",
            f"- Application URLs found: {sum(1 for r in kept if r.application_url)}",
            f"- Application pages accessible: "
            f"{sum(1 for r in kept if r.verification.application_page_accessible)}",
            f"- Active confirmed: "
            f"{sum(1 for r in kept if r.verification.active_status_confirmed)}",
            f"- Expired/closed excluded: {len(closed)}",
            f"- Iterations: {metrics.iterations}",
            f"- URLs investigated: {metrics.urls_investigated}",
            f"- Completion score: "
            f"{evaluation.completion_score if evaluation else 'n/a'}",
            f"- Incomplete: {'yes' if incomplete else 'no'}",
            "",
            "## Gaps / uncertainties",
        ]
    )
    gaps = (evaluation.missing_information if evaluation else []) or []
    if not gaps and not incomplete:
        lines.append("- None noted.")
    else:
        for gap in gaps:
            lines.append(f"- {gap}")
        if incomplete:
            lines.append(
                "- Stopped due to iteration/time/token budget or incomplete verification."
            )

    lines.extend(
        [
            "",
            "## Next",
            "Reply with a number to dig into that role, or refine location/seniority.",
        ]
    )
    return "\n".join(lines)


async def _general_markdown(
    router: ModelRouter,
    user_objective: str,
    plan: ResearchPlan,
    records: list[JobRecord],
    evaluation: EvaluationResult | None,
    metrics: ResearchMetrics,
    incomplete: bool,
) -> str:
    sources = []
    for record in records[:12]:
        sources.append(
            {
                "title": record.role or record.company,
                "url": record.job_url or record.source_url,
                "status": record.status,
                "notes": record.notes,
            }
        )
    response = await router.complete(
        "synthesize",
        [
            {
                "role": "system",
                "content": (
                    "Write a concise research brief with citations. "
                    "Do not invent sources. State uncertainties clearly. "
                    "Keep full https URLs visible in the text."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Objective: {user_objective}\n"
                    f"Plan: {plan.model_dump()}\n"
                    f"Sources/records: {sources}\n"
                    f"Evaluation: {evaluation.model_dump() if evaluation else {}}\n"
                    f"Metrics: {metrics.model_dump()}\n"
                    f"Incomplete: {incomplete}\n"
                ),
            },
        ],
        max_tokens=2000,
    )
    return (response.text or "").strip() or "No synthesis produced."
