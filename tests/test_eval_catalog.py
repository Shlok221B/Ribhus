"""Run the hermetic eval catalog through pytest."""

from __future__ import annotations

import pytest

from ribhus.eval.catalog import load_catalog
from ribhus.eval.runner import run_case


def _ids() -> list[str]:
    return [case.id for case in load_catalog()]


@pytest.mark.parametrize("case", load_catalog(), ids=_ids())
async def test_eval_case(case) -> None:
    result = await run_case(case)
    if result.status == "skip":
        pytest.skip(result.detail)
    assert result.status == "pass", result.detail


def test_catalog_ids_unique() -> None:
    cases = load_catalog()
    ids = [c.id for c in cases]
    assert ids
    assert len(ids) == len(set(ids))
    assert {c.category for c in cases} >= {
        "basic",
        "agentic",
        "safety",
        "skills",
        "india",
        "memory",
        "whatsapp",
        "gmail",
        "mcp",
        "dashboard",
        "cli",
    }
