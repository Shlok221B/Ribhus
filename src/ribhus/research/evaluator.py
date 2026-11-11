"""Research quality evaluator — decides whether to iterate."""

from __future__ import annotations

from typing import Any

from ribhus.models.router import ModelRouter
from ribhus.research.models import (
    EvaluationResult,
    JobRecord,
    ResearchPlan,
    SearchLead,
)

_EVAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "research_complete": {"type": "boolean"},
        "completion_score": {"type": "integer"},
        "missing_information": {"type": "array", "items": {"type": "string"}},
        "next_search_queries": {"type": "array", "items": {"type": "string"}},
        "next_actions": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
    },
    "required": [
        "research_complete",
        "completion_score",
        "missing_information",
        "next_search_queries",
        "next_actions",
        "rationale",
    ],
}


async def evaluate_research(
    router: ModelRouter,
    *,
    user_objective: str,
    plan: ResearchPlan,
    queries: list[str],
    leads: list[SearchLead],
    records: list[JobRecord],
    iteration: int,
    max_iterations: int,
) -> EvaluationResult:
    heuristic = _heuristic_eval(plan, records, leads, iteration, max_iterations)

    summary_records = [
        {
            "company": r.company,
            "role": r.role,
            "location": r.location,
            "experience": r.experience,
            "job_url": r.job_url,
            "application_url": r.application_url,
            "status": r.status,
            "verification": r.verification.model_dump(),
        }
        for r in records[:20]
    ]
    data = await router.complete_json(
        "evaluate",
        [
            {
                "role": "system",
                "content": (
                    "You evaluate deep research completeness. "
                    "Do not invent listings. Prefer more direct application URLs "
                    "and verified active pages. Propose NEW search queries only "
                    "for missing gaps — never repeat prior queries. JSON only."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User objective: {user_objective}\n"
                    f"Plan: {plan.model_dump()}\n"
                    f"Iteration: {iteration}/{max_iterations}\n"
                    f"Queries used: {queries}\n"
                    f"Leads found: {len(leads)}\n"
                    f"Records: {summary_records}\n"
                    f"Heuristic suggestion: {heuristic.model_dump()}\n"
                ),
            },
        ],
        json_schema=_EVAL_SCHEMA,
        max_tokens=1000,
    )
    if not data:
        return heuristic

    score = int(data.get("completion_score") or heuristic.completion_score)
    score = max(0, min(100, score))
    complete = bool(data.get("research_complete"))
    # Never mark complete if we have zero actionable records for jobs
    if plan.domain == "jobs":
        actionable = [
            r
            for r in records
            if r.status != "closed" and (r.job_url or r.application_url) and r.role
        ]
        if len(actionable) < 3:
            complete = False
            score = min(score, 55)

    if iteration >= max_iterations:
        complete = True  # stop loop; synthesizer will report limitations

    prior = {q.lower().strip() for q in queries}
    next_q = [
        str(q).strip()
        for q in (data.get("next_search_queries") or [])
        if str(q).strip() and str(q).strip().lower() not in prior
    ]

    return EvaluationResult(
        research_complete=complete,
        completion_score=score,
        missing_information=[
            str(x) for x in (data.get("missing_information") or []) if x
        ]
        or heuristic.missing_information,
        next_search_queries=next_q or heuristic.next_search_queries,
        next_actions=[str(x) for x in (data.get("next_actions") or []) if x]
        or heuristic.next_actions,
        rationale=str(data.get("rationale") or heuristic.rationale),
    )


def _heuristic_eval(
    plan: ResearchPlan,
    records: list[JobRecord],
    leads: list[SearchLead],
    iteration: int,
    max_iterations: int,
) -> EvaluationResult:
    if plan.domain != "jobs":
        score = min(90, 20 + len(records) * 15 + (10 if leads else 0))
        complete = score >= 70 or iteration >= max_iterations
        return EvaluationResult(
            research_complete=complete,
            completion_score=score,
            missing_information=[] if complete else ["More primary sources"],
            next_search_queries=[],
            next_actions=[] if complete else ["search_additional_sources"],
            rationale="Heuristic general research score",
        )

    open_records = [r for r in records if r.status != "closed"]
    with_apply = [r for r in open_records if r.application_url]
    verified = [
        r
        for r in open_records
        if r.verification.application_page_accessible
        or r.status in {"application_accessible", "active_confirmed"}
    ]
    missing: list[str] = []
    next_actions: list[str] = []
    next_queries: list[str] = []

    if len(open_records) < 5:
        missing.append("More individual job listings")
        next_actions.append("search_additional_sources")
        next_queries.append(f"{plan.objective} careers")
    if len(with_apply) < max(3, len(open_records) // 2):
        missing.append("More direct company application pages")
        next_actions.append("inspect_job_pages")
        next_queries.append(
            f"{plan.constraints.get('role', 'developer')} "
            "site:greenhouse.io OR site:lever.co OR site:ashbyhq.com"
        )
    if len(verified) < max(2, len(with_apply) // 2):
        missing.append("Verification of active job listings")
        next_actions.append("verify_application_urls")

    score = 0
    score += min(40, len(open_records) * 6)
    score += min(30, len(with_apply) * 6)
    score += min(20, len(verified) * 5)
    score += 10 if leads else 0
    score = min(100, score)
    complete = score >= 75 and len(open_records) >= 5 and len(with_apply) >= 3
    if iteration >= max_iterations:
        complete = True

    return EvaluationResult(
        research_complete=complete,
        completion_score=score,
        missing_information=missing,
        next_search_queries=next_queries,
        next_actions=next_actions,
        rationale="Heuristic job-research scoring",
    )
