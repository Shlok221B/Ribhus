"""Search query generation for research iterations."""

from __future__ import annotations

from typing import Any

from ribhus.models.router import ModelRouter
from ribhus.research.canonical import query_fingerprint
from ribhus.research.models import ResearchPlan

_QUERY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "queries": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 10,
        }
    },
    "required": ["queries"],
}


async def generate_search_queries(
    router: ModelRouter,
    plan: ResearchPlan,
    *,
    missing_information: list[str] | None = None,
    next_search_queries: list[str] | None = None,
    prior_queries: list[str] | None = None,
    iteration: int = 1,
) -> list[str]:
    prior = list(prior_queries or [])
    prior_fps = {query_fingerprint(q) for q in prior}

    seeded = [q.strip() for q in (next_search_queries or []) if q and q.strip()]
    if iteration == 1 and not seeded:
        seeded = _seed_queries(plan)

    user = (
        f"Research objective: {plan.objective}\n"
        f"Domain: {plan.domain}\n"
        f"Constraints: {plan.constraints}\n"
        f"Strategies: {plan.search_strategies}\n"
        f"Iteration: {iteration}\n"
        f"Missing information: {missing_information or []}\n"
        f"Suggested next queries: {seeded}\n"
        f"Already used queries (do NOT repeat): {prior}\n\n"
        "Produce 4–8 DISTINCT web search queries that discover primary pages "
        "(job listings, ATS, careers), not generic advice articles."
    )
    data = await router.complete_json(
        "query_gen",
        [
            {
                "role": "system",
                "content": (
                    "You generate diverse web search queries for deep research. "
                    "Vary synonyms, site: filters, and angles. JSON only."
                ),
            },
            {"role": "user", "content": user},
        ],
        json_schema=_QUERY_SCHEMA,
        max_tokens=800,
    )
    raw = [str(q).strip() for q in (data.get("queries") or []) if str(q).strip()]
    if not raw:
        raw = seeded or _seed_queries(plan)

    unique: list[str] = []
    seen = set(prior_fps)
    for query in [*seeded, *raw]:
        fp = query_fingerprint(query)
        if fp in seen:
            continue
        seen.add(fp)
        unique.append(query)
        if len(unique) >= 8:
            break
    return unique


def _seed_queries(plan: ResearchPlan) -> list[str]:
    obj = plan.objective
    constraints = plan.constraints or {}
    role = str(constraints.get("role") or constraints.get("title") or "").strip()
    location = str(
        constraints.get("location") or constraints.get("city") or ""
    ).strip()
    experience = str(constraints.get("experience") or "").strip()

    if plan.domain != "jobs":
        return [
            obj,
            f"{obj} primary sources",
            f"{obj} official",
        ]

    base_role = role or obj
    loc = location or "India"
    queries = [
        f"{base_role} jobs {loc}",
        f"{base_role} {loc} site:greenhouse.io OR site:lever.co OR site:ashbyhq.com",
        f"{base_role} jobs site:linkedin.com/jobs",
        f"{base_role} careers hiring {loc}",
        f"{base_role} site:naukri.com OR site:cutshort.io OR site:instahyre.com",
        f"{base_role} FastAPI OR Django hiring {loc}",
    ]
    if experience:
        queries.append(f"{base_role} {experience} years {loc}")
    # Deduplicate while preserving order
    out: list[str] = []
    seen: set[str] = set()
    for q in queries:
        fp = query_fingerprint(q)
        if fp in seen:
            continue
        seen.add(fp)
        out.append(q)
    return out
