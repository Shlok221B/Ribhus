"""Research quality evaluator — decides whether to iterate."""

from __future__ import annotations

from typing import Any

from ribhus.models.router import ModelRouter
from ribhus.research.canonical import query_fingerprint
from ribhus.research.models import (
    EvaluationResult,
    JobRecord,
    ResearchPlan,
    SearchLead,
)
from ribhus.research.quality import constraint_satisfaction_score

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


def _dedupe_queries(candidates: list[str], prior: list[str]) -> list[str]:
    seen = {query_fingerprint(q) for q in prior}
    out: list[str] = []
    for query in candidates:
        text = str(query).strip()
        if not text:
            continue
        fp = query_fingerprint(text)
        if fp in seen:
            continue
        seen.add(fp)
        out.append(text)
    return out


def jobs_quality_met(records: list[JobRecord], plan: ResearchPlan) -> bool:
    open_records = [r for r in records if r.status != "closed"]
    with_apply = [r for r in open_records if r.application_url]
    verified = [
        r
        for r in open_records
        if r.verification.application_page_accessible
        or r.status in {"application_accessible", "active_confirmed"}
    ]
    satisfaction = constraint_satisfaction_score(open_records, plan) or 0.0
    return (
        len(open_records) >= 5
        and len(with_apply) >= 3
        and len(verified) >= 2
        and satisfaction >= 0.5
    )


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
    new_leads_this_round: int = 0,
) -> EvaluationResult:
    heuristic = _heuristic_eval(
        plan,
        records,
        leads,
        iteration,
        max_iterations,
        new_leads_this_round=new_leads_this_round,
    )

    summary_records = [
        {
            "company": r.company,
            "role": r.role,
            "location": r.location,
            "experience": r.experience,
            "job_url": r.job_url,
            "application_url": r.application_url,
            "status": r.status,
            "verification": {
                "apply_page": r.verification.application_page_accessible,
                "active": r.verification.active_status_confirmed,
                "title_confirmed": r.verification.title_confirmed,
            },
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
                    "for missing gaps — never repeat prior queries. "
                    "If results are thin, set research_complete=false. JSON only."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User objective: {user_objective}\n"
                    f"Plan: {plan.model_dump()}\n"
                    f"Iteration: {iteration}/{max_iterations}\n"
                    f"Queries used: {queries}\n"
                    f"Leads found: {len(leads)} (new this round: {new_leads_this_round})\n"
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

    llm_score = int(data.get("completion_score") or heuristic.completion_score)
    llm_score = max(0, min(100, llm_score))
    # Blend — never let LLM alone inflate past heuristic + 15
    score = min(llm_score, heuristic.completion_score + 15)
    score = max(score, min(llm_score, heuristic.completion_score))

    quality = (
        jobs_quality_met(records, plan)
        if plan.domain == "jobs"
        else heuristic.quality_met
    )
    complete = bool(data.get("research_complete")) and quality
    if plan.domain == "jobs" and not quality:
        complete = False
        score = min(score, 70)

    stop_reason = None
    if complete and quality:
        stop_reason = "quality_met"
    elif iteration >= max_iterations:
        # Stop the loop, but do not pretend quality was met
        complete = True
        stop_reason = "max_iterations"
        quality = quality  # may still be False

    if new_leads_this_round == 0 and iteration > 1 and not quality:
        # Suggest stopping if search is exhausted
        if not (data.get("next_search_queries") or heuristic.next_search_queries):
            complete = True
            stop_reason = stop_reason or "no_new_leads"

    next_q = _dedupe_queries(
        [str(q) for q in (data.get("next_search_queries") or [])],
        queries,
    )
    if not next_q:
        next_q = _dedupe_queries(heuristic.next_search_queries, queries)

    return EvaluationResult(
        research_complete=complete,
        completion_score=score,
        missing_information=[
            str(x) for x in (data.get("missing_information") or []) if x
        ]
        or heuristic.missing_information,
        next_search_queries=next_q,
        next_actions=[str(x) for x in (data.get("next_actions") or []) if x]
        or heuristic.next_actions,
        rationale=str(data.get("rationale") or heuristic.rationale),
        stop_reason=stop_reason,
        quality_met=quality,
    )


def _heuristic_eval(
    plan: ResearchPlan,
    records: list[JobRecord],
    leads: list[SearchLead],
    iteration: int,
    max_iterations: int,
    *,
    new_leads_this_round: int = 0,
) -> EvaluationResult:
    if plan.domain != "jobs":
        score = min(90, 20 + len(records) * 15 + (10 if leads else 0))
        quality = score >= 70 and len(records) >= 3
        complete = quality
        stop_reason = "quality_met" if complete else None
        if iteration >= max_iterations:
            complete = True
            stop_reason = stop_reason or "max_iterations"
        return EvaluationResult(
            research_complete=complete,
            completion_score=score,
            missing_information=[] if quality else ["More primary sources"],
            next_search_queries=[]
            if quality
            else [f"{plan.objective} primary sources", f"{plan.objective} official"],
            next_actions=[] if quality else ["search_additional_sources"],
            rationale="Heuristic general research score",
            stop_reason=stop_reason,
            quality_met=quality,
        )

    open_records = [r for r in records if r.status != "closed"]
    with_apply = [r for r in open_records if r.application_url]
    verified = [
        r
        for r in open_records
        if r.verification.application_page_accessible
        or r.status in {"application_accessible", "active_confirmed"}
    ]
    role = str((plan.constraints or {}).get("role") or "developer")
    loc = str(
        (plan.constraints or {}).get("location")
        or (plan.constraints or {}).get("remote")
        or ""
    )
    missing: list[str] = []
    next_actions: list[str] = []
    next_queries: list[str] = []

    if len(open_records) < 5:
        missing.append("More individual job listings")
        next_actions.append("search_additional_sources")
        next_queries.append(f"{role} jobs {loc}".strip())
        next_queries.append(f"{role} hiring {loc} careers".strip())
    if len(with_apply) < max(3, len(open_records) // 2 or 1):
        missing.append("More direct company application pages")
        next_actions.append("inspect_job_pages")
        next_queries.append(
            f"{role} site:greenhouse.io OR site:lever.co OR site:ashbyhq.com {loc}".strip()
        )
    if len(verified) < max(2, len(with_apply) // 2 or 1):
        missing.append("Verification of active job listings")
        next_actions.append("verify_application_urls")
        next_queries.append(f"{role} {loc} site:myworkdayjobs.com OR site:wellfound.com")

    score = 0
    score += min(40, len(open_records) * 6)
    score += min(30, len(with_apply) * 6)
    score += min(20, len(verified) * 5)
    score += 10 if leads else 0
    satisfaction = constraint_satisfaction_score(open_records, plan)
    if satisfaction is not None:
        score = int(score * (0.7 + 0.3 * satisfaction))
    score = min(100, score)

    quality = jobs_quality_met(records, plan)
    complete = quality
    stop_reason = "quality_met" if quality else None
    if iteration >= max_iterations:
        complete = True
        stop_reason = stop_reason or "max_iterations"
    if new_leads_this_round == 0 and iteration > 1 and not quality:
        next_queries = next_queries  # still try alternate angles once

    return EvaluationResult(
        research_complete=complete,
        completion_score=score,
        missing_information=missing,
        next_search_queries=next_queries,
        next_actions=next_actions,
        rationale="Heuristic job-research scoring",
        stop_reason=stop_reason,
        quality_met=quality,
    )
