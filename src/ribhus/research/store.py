"""SQLite persistence for research runs (no Redis)."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ribhus.research.canonical import record_fingerprint
from ribhus.research.models import (
    EvaluationResult,
    JobRecord,
    ResearchMetrics,
    ResearchPlan,
    SearchLead,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS research_runs (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    objective TEXT NOT NULL,
    status TEXT NOT NULL,
    plan_json TEXT,
    evaluation_json TEXT,
    metrics_json TEXT,
    usage_json TEXT,
    summary TEXT,
    incomplete INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_research_runs_task ON research_runs(task_id);

CREATE TABLE IF NOT EXISTS research_queries (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    iteration INTEGER NOT NULL,
    provider TEXT,
    query TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_research_queries_run ON research_queries(run_id);
CREATE INDEX IF NOT EXISTS idx_research_queries_fp ON research_queries(fingerprint);

CREATE TABLE IF NOT EXISTS research_leads (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    iteration INTEGER NOT NULL,
    url TEXT NOT NULL,
    canonical_url TEXT,
    title TEXT,
    snippet TEXT,
    provider TEXT,
    query TEXT,
    score REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_research_leads_run ON research_leads(run_id);
CREATE INDEX IF NOT EXISTS idx_research_leads_canon ON research_leads(canonical_url);

CREATE TABLE IF NOT EXISTS research_records (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    fingerprint TEXT,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_research_records_run ON research_records(run_id);

CREATE TABLE IF NOT EXISTS research_iterations (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    iteration INTEGER NOT NULL,
    evaluation_json TEXT,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class ResearchStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def create_run(
        self,
        *,
        objective: str,
        task_id: str | None = None,
        plan: ResearchPlan | None = None,
    ) -> str:
        run_id = _new_id("rr")
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO research_runs
                (id, task_id, objective, status, plan_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    task_id,
                    objective,
                    "running",
                    json.dumps(plan.model_dump()) if plan else None,
                    now,
                    now,
                ),
            )
            conn.commit()
        return run_id

    def update_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        plan: ResearchPlan | None = None,
        evaluation: EvaluationResult | None = None,
        metrics: ResearchMetrics | None = None,
        usage: dict[str, Any] | None = None,
        summary: str | None = None,
        incomplete: bool | None = None,
    ) -> None:
        fields: list[str] = ["updated_at = ?"]
        values: list[Any] = [_now()]
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if plan is not None:
            fields.append("plan_json = ?")
            values.append(json.dumps(plan.model_dump()))
        if evaluation is not None:
            fields.append("evaluation_json = ?")
            values.append(json.dumps(evaluation.model_dump()))
        if metrics is not None:
            fields.append("metrics_json = ?")
            values.append(json.dumps(metrics.model_dump()))
        if usage is not None:
            fields.append("usage_json = ?")
            values.append(json.dumps(usage))
        if summary is not None:
            fields.append("summary = ?")
            values.append(summary)
        if incomplete is not None:
            fields.append("incomplete = ?")
            values.append(1 if incomplete else 0)
        values.append(run_id)
        with self._lock, self._connect() as conn:
            conn.execute(
                f"UPDATE research_runs SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            conn.commit()

    def add_queries(
        self,
        run_id: str,
        iteration: int,
        queries: list[str],
        *,
        fingerprints: list[str],
        provider: str = "multi",
    ) -> None:
        now = _now()
        rows = [
            (_new_id("rq"), run_id, iteration, provider, q, fp, now)
            for q, fp in zip(queries, fingerprints, strict=False)
        ]
        if not rows:
            return
        with self._lock, self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO research_queries
                (id, run_id, iteration, provider, query, fingerprint, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()

    def add_leads(
        self, run_id: str, iteration: int, leads: list[SearchLead]
    ) -> None:
        now = _now()
        rows = [
            (
                _new_id("rl"),
                run_id,
                iteration,
                lead.url,
                lead.canonical_url,
                lead.title,
                lead.snippet,
                lead.provider,
                lead.query,
                lead.score,
                now,
            )
            for lead in leads
        ]
        if not rows:
            return
        with self._lock, self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO research_leads
                (id, run_id, iteration, url, canonical_url, title, snippet,
                 provider, query, score, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()

    def add_iteration(
        self, run_id: str, iteration: int, evaluation: EvaluationResult
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO research_iterations
                (id, run_id, iteration, evaluation_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    _new_id("ri"),
                    run_id,
                    iteration,
                    json.dumps(evaluation.model_dump()),
                    _now(),
                ),
            )
            conn.commit()

    def replace_records(self, run_id: str, records: list[JobRecord]) -> None:
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM research_records WHERE run_id = ?", (run_id,))
            rows = [
                (
                    _new_id("rc"),
                    run_id,
                    record_fingerprint(record.company, record.role, record.job_url),
                    json.dumps(record.model_dump()),
                    now,
                )
                for record in records
            ]
            if rows:
                conn.executemany(
                    """
                    INSERT INTO research_records
                    (id, run_id, fingerprint, record_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    rows,
                )
            conn.commit()

    def load_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM research_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return dict(row) if row else None

    def latest_for_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM research_runs
                WHERE task_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (task_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_run_detail(self, run_id: str) -> dict[str, Any] | None:
        run = self.load_run(run_id)
        if run is None:
            return None
        with self._lock, self._connect() as conn:
            queries = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT iteration, provider, query, fingerprint, created_at
                    FROM research_queries WHERE run_id = ?
                    ORDER BY iteration, created_at
                    """,
                    (run_id,),
                ).fetchall()
            ]
            leads = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT iteration, url, canonical_url, title, provider, score
                    FROM research_leads WHERE run_id = ?
                    ORDER BY score DESC
                    LIMIT 100
                    """,
                    (run_id,),
                ).fetchall()
            ]
            records_raw = conn.execute(
                """
                SELECT fingerprint, record_json, created_at
                FROM research_records WHERE run_id = ?
                """,
                (run_id,),
            ).fetchall()
            iterations = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT iteration, evaluation_json, created_at
                    FROM research_iterations WHERE run_id = ?
                    ORDER BY iteration
                    """,
                    (run_id,),
                ).fetchall()
            ]
        records: list[dict[str, Any]] = []
        for row in records_raw:
            try:
                payload = json.loads(row["record_json"])
            except json.JSONDecodeError:
                payload = {}
            records.append(
                {
                    "fingerprint": row["fingerprint"],
                    "created_at": row["created_at"],
                    "record": payload,
                }
            )
        return {
            "run": run,
            "plan": _json_or_none(run.get("plan_json")),
            "evaluation": _json_or_none(run.get("evaluation_json")),
            "metrics": _json_or_none(run.get("metrics_json")),
            "usage": _json_or_none(run.get("usage_json")),
            "queries": queries,
            "leads": leads,
            "records": records,
            "iterations": [
                {
                    "iteration": item["iteration"],
                    "created_at": item["created_at"],
                    "evaluation": _json_or_none(item.get("evaluation_json")),
                }
                for item in iterations
            ],
        }

    def list_recent(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, task_id, objective, status, incomplete, created_at, updated_at,
                       metrics_json
                FROM research_runs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(1, min(limit, 100)),),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["metrics"] = _json_or_none(item.pop("metrics_json", None))
            out.append(item)
        return out


def _json_or_none(raw: Any) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
