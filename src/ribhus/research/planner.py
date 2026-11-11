"""Autonomous research planner — structured JSON plans."""

from __future__ import annotations

import json
import re
from typing import Any

from ribhus.models.router import ModelRouter
from ribhus.research.models import ResearchObjective, ResearchPlan

_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "objective": {"type": "string"},
        "constraints": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "role": {"type": "string"},
                "location": {"type": "string"},
                "remote": {"type": "string"},
                "experience": {"type": "string"},
                "seniority": {"type": "string"},
                "skills": {"type": "array", "items": {"type": "string"}},
                "must_haves": {"type": "array", "items": {"type": "string"}},
            },
            "required": [],
        },
        "information_needed": {
            "type": "array",
            "items": {"type": "string"},
        },
        "research_objectives": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "description": {"type": "string"},
                    "success_criteria": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["id", "description", "success_criteria"],
            },
        },
        "search_strategies": {
            "type": "array",
            "items": {"type": "string"},
        },
        "success_definition": {"type": "string"},
        "domain": {"type": "string", "enum": ["jobs", "general"]},
    },
    "required": [
        "objective",
        "constraints",
        "information_needed",
        "research_objectives",
        "search_strategies",
        "success_definition",
        "domain",
    ],
}

_PLANNER_SYSTEM = """You are Ribhus research planner. Produce a structured research plan as JSON.
Do not invent facts. Focus on what must be discovered on the live web.
For job searches: include strategies for ATS boards (Greenhouse, Lever, Ashby),
company career pages, and direct application URLs. Treat search engine hits as leads only.
Set domain to "jobs" when the user wants openings/hiring/roles to apply to; otherwise "general".
"""


async def build_research_plan(
    router: ModelRouter,
    user_objective: str,
    *,
    skill_hint: str = "",
) -> ResearchPlan:
    user = (
        f"User request:\n{user_objective.strip()}\n\n"
        "Return a research plan with concrete objectives and search strategies."
    )
    if skill_hint.strip():
        user += f"\n\nDomain skill guidance (follow for output expectations):\n{skill_hint[:4000]}"

    data = await router.complete_json(
        "plan",
        [
            {"role": "system", "content": _PLANNER_SYSTEM},
            {"role": "user", "content": user},
        ],
        json_schema=_PLAN_SCHEMA,
        max_tokens=2000,
    )
    if not data:
        return _fallback_plan(user_objective)
    plan = _plan_from_dict(data, fallback_objective=user_objective)
    # Fill missing common job constraints from the raw objective
    if plan.domain == "jobs":
        inferred = _infer_job_constraints(user_objective)
        merged = {**inferred, **(plan.constraints or {})}
        plan.constraints = merged
    return plan


def _plan_from_dict(data: dict[str, Any], *, fallback_objective: str) -> ResearchPlan:
    objectives: list[ResearchObjective] = []
    for i, item in enumerate(data.get("research_objectives") or []):
        if not isinstance(item, dict):
            continue
        objectives.append(
            ResearchObjective(
                id=str(item.get("id") or f"obj-{i + 1}"),
                description=str(item.get("description") or ""),
                success_criteria=[
                    str(c) for c in (item.get("success_criteria") or []) if c
                ],
            )
        )
    domain = str(data.get("domain") or "general").lower()
    if domain not in {"jobs", "general"}:
        domain = (
            "jobs"
            if any(
                w in fallback_objective.lower()
                for w in ("job", "hiring", "opening", "career")
            )
            else "general"
        )
    constraints = data.get("constraints")
    if not isinstance(constraints, dict):
        constraints = {}
    return ResearchPlan(
        objective=str(data.get("objective") or fallback_objective).strip()
        or fallback_objective,
        constraints=constraints,
        information_needed=[
            str(x) for x in (data.get("information_needed") or []) if x
        ],
        research_objectives=objectives
        or [
            ResearchObjective(
                id="obj-1",
                description="Discover and verify relevant results",
                success_criteria=["At least several verified primary sources"],
            )
        ],
        search_strategies=[
            str(x) for x in (data.get("search_strategies") or []) if x
        ],
        success_definition=str(data.get("success_definition") or "").strip(),
        domain=domain,  # type: ignore[arg-type]
    )


def _infer_job_constraints(objective: str) -> dict[str, Any]:
    text = objective.strip()
    lower = text.lower()
    constraints: dict[str, Any] = {}
    exp = None
    for pattern in (
        r"(\d+\s*[-–to]+\s*\d+\s*years?)",
        r"(\d+\+?\s*years?)",
    ):
        match = re.search(pattern, lower)
        if match:
            exp = match.group(1)
            break
    if exp:
        constraints["experience"] = exp
    if "remote" in lower and "india" in lower:
        constraints["location"] = "Pune or remote India" if "pune" in lower else "Remote India"
        constraints["remote"] = "remote India"
    elif "pune" in lower:
        constraints["location"] = "Pune"
    elif "bengaluru" in lower or "bangalore" in lower:
        constraints["location"] = "Bengaluru"
    elif "india" in lower:
        constraints["location"] = "India"
    role = None
    for needle in (
        "python backend developer",
        "python backend engineer",
        "backend developer",
        "backend engineer",
        "fastapi developer",
        "django developer",
    ):
        if needle in lower:
            role = needle.title().replace("Fastapi", "FastAPI")
            break
    if role:
        constraints["role"] = role
    return constraints


def _fallback_plan(user_objective: str) -> ResearchPlan:
    text = user_objective.lower()
    jobs = any(w in text for w in ("job", "hiring", "opening", "career", "apply"))
    if jobs:
        return ResearchPlan(
            objective=user_objective.strip(),
            constraints=_infer_job_constraints(user_objective),
            information_needed=[
                "Individual job listings",
                "Company and role titles",
                "Location / remote fit",
                "Experience requirements",
                "Direct application URLs",
                "Active vs closed status",
            ],
            research_objectives=[
                ResearchObjective(
                    id="companies",
                    description="Find companies hiring for the role",
                    success_criteria=["Named employers with careers evidence"],
                ),
                ResearchObjective(
                    id="listings",
                    description="Find individual job postings",
                    success_criteria=["Direct listing URLs opened and extracted"],
                ),
                ResearchObjective(
                    id="ats",
                    description="Search Greenhouse / Lever / Ashby and career pages",
                    success_criteria=["ATS or careers pages inspected"],
                ),
                ResearchObjective(
                    id="verify",
                    description="Verify listings and application URLs",
                    success_criteria=["Application link accessibility checked"],
                ),
            ],
            search_strategies=[
                "Role + location job board queries",
                "site:greenhouse.io / lever.co / ashbyhq.com",
                "Company careers pages",
                "India boards when location is India",
            ],
            success_definition=(
                "Ranked openings with company, role, location, apply URL, "
                "and verification status; no fabricated listings."
            ),
            domain="jobs",
        )
    return ResearchPlan(
        objective=user_objective.strip(),
        constraints={},
        information_needed=["Primary sources", "Verified facts", "Citations"],
        research_objectives=[
            ResearchObjective(
                id="discover",
                description="Discover relevant sources",
                success_criteria=["Multiple distinct primary URLs"],
            ),
            ResearchObjective(
                id="verify",
                description="Open and extract from primary pages",
                success_criteria=["Facts tied to source URLs"],
            ),
        ],
        search_strategies=["Multi-angle web search", "Primary page inspection"],
        success_definition="Actionable findings with citations; unknowns stated.",
        domain="general",
    )


def plan_to_prompt_block(plan: ResearchPlan) -> str:
    return json.dumps(plan.model_dump(), indent=2)
