from __future__ import annotations

import inspect
import time
import traceback
from collections.abc import Sequence

from ribhus.eval.catalog import load_catalog
from ribhus.eval.models import EvalCase, EvalResult, EvalSkip


async def run_case(case: EvalCase) -> EvalResult:
    started = time.perf_counter()
    try:
        outcome = case.fn()
        if inspect.isawaitable(outcome):
            await outcome
    except EvalSkip as skip:
        ms = (time.perf_counter() - started) * 1000
        return EvalResult(case=case, status="skip", detail=skip.reason, duration_ms=ms)
    except Exception as extra:  # noqa: BLE001 — surface assertion/runtime failures
        ms = (time.perf_counter() - started) * 1000
        detail = f"{type(extra).__name__}: {extra}"
        tb = traceback.format_exc(limit=6)
        return EvalResult(
            case=case,
            status="fail",
            detail=f"{detail}\n{tb}".strip(),
            duration_ms=ms,
        )
    ms = (time.perf_counter() - started) * 1000
    return EvalResult(case=case, status="pass", duration_ms=ms)


async def run_catalog(
    cases: Sequence[EvalCase] | None = None,
    *,
    category: str | None = None,
) -> list[EvalResult]:
    selected = list(cases if cases is not None else load_catalog())
    if category:
        wanted = category.strip().lower()
        selected = [c for c in selected if c.category.lower() == wanted]
        if not selected:
            raise ValueError(
                f"No eval cases in category {category!r}. "
                f"Try: {', '.join(sorted({c.category for c in load_catalog()}))}"
            )
    return [await run_case(case) for case in selected]


def run_eval_cli(*, category: str | None = None, json_out: bool = False) -> int:
    import asyncio

    from ribhus.eval.report import print_json, print_table

    results = asyncio.run(run_catalog(category=category))
    if json_out:
        print_json(results)
    else:
        print_table(results)
    return 1 if any(r.status == "fail" for r in results) else 0
