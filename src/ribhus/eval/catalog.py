from __future__ import annotations

from ribhus.eval.cases import (
    agentic,
    basic,
    cli,
    dashboard,
    gmail,
    india,
    mcp,
    memory,
    safety,
    skills,
    whatsapp,
)
from ribhus.eval.models import EvalCase

_MODULES = (
    basic,
    agentic,
    safety,
    skills,
    india,
    memory,
    whatsapp,
    gmail,
    mcp,
    dashboard,
    cli,
)


def load_catalog() -> list[EvalCase]:
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for module in _MODULES:
        for case in module.CASES:
            if case.id in seen:
                raise ValueError(f"Duplicate eval id: {case.id}")
            seen.add(case.id)
            cases.append(case)
    return cases
