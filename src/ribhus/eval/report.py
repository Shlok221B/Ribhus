from __future__ import annotations

import json
from collections import Counter

from rich.console import Console
from rich.table import Table

from ribhus.eval.models import EvalResult

_STYLE = {"pass": "green", "fail": "red", "skip": "yellow"}


def print_table(results: list[EvalResult], *, console: Console | None = None) -> None:
    out = console or Console()
    table = Table(title="Ribhus hermetic evals")
    table.add_column("Category")
    table.add_column("ID")
    table.add_column("Feature")
    table.add_column("Status")
    table.add_column("Detail", overflow="fold")
    for result in results:
        style = _STYLE.get(result.status, "")
        detail = result.detail.splitlines()[0] if result.detail else ""
        if len(detail) > 120:
            detail = detail[:117] + "…"
        table.add_row(
            result.case.category,
            result.case.id,
            result.case.feature,
            f"[{style}]{result.status}[/{style}]",
            detail,
        )
    out.print(table)
    counts = Counter(r.status for r in results)
    out.print(
        f"[bold]{len(results)}[/bold] cases  "
        f"[green]{counts.get('pass', 0)} pass[/green]  "
        f"[red]{counts.get('fail', 0)} fail[/red]  "
        f"[yellow]{counts.get('skip', 0)} skip[/yellow]"
    )


def print_json(results: list[EvalResult]) -> None:
    payload = {
        "summary": dict(Counter(r.status for r in results)),
        "results": [
            {
                "id": r.case.id,
                "category": r.case.category,
                "feature": r.case.feature,
                "title": r.case.title,
                "status": r.status,
                "detail": r.detail,
                "duration_ms": round(r.duration_ms, 2),
            }
            for r in results
        ],
    }
    print(json.dumps(payload, indent=2))
