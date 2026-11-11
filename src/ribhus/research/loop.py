"""Autonomous multi-step research orchestrator."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from ribhus.agent.deep_research import looks_deep_research
from ribhus.config import Settings
from ribhus.models.openai_compatible import OpenAICompatibleModel
from ribhus.models.router import ModelRouter
from ribhus.research.canonical import query_fingerprint
from ribhus.research.evaluator import evaluate_research
from ribhus.research.extract import extract_job_from_snapshot, extract_job_with_llm
from ribhus.research.inspect.escalate import investigate_leads
from ribhus.research.metrics import compute_metrics
from ribhus.research.models import JobRecord, ResearchResult
from ribhus.research.planner import build_research_plan
from ribhus.research.queries import generate_search_queries
from ribhus.research.search import build_search_providers, multi_search
from ribhus.research.store import ResearchStore
from ribhus.research.synthesizer import synthesize_results
from ribhus.research.verify import dedupe_records, verify_records
from ribhus.tools.browser import BrowserSession

logger = logging.getLogger(__name__)

EventCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]

_JOB_SKILL_HINTS = frozenset({"job-search", "jobs"})


def should_run_research(
    prompt: str,
    *,
    settings: Settings,
    skill_names: list[str] | None = None,
) -> bool:
    if not settings.research_enabled:
        return False
    names = {n.lower() for n in (skill_names or [])}
    if names & _JOB_SKILL_HINTS or "company-research" in names:
        return True
    return looks_deep_research(prompt)


class ResearchOrchestrator:
    def __init__(
        self,
        settings: Settings,
        *,
        router: ModelRouter | None = None,
        browser: BrowserSession | None = None,
        store: ResearchStore | None = None,
        on_event: EventCallback | None = None,
    ) -> None:
        self.settings = settings
        self.router = router or ModelRouter(settings)
        self.browser = browser
        self.store = store or ResearchStore(settings.ribhus_dir / "research.sqlite")
        self.on_event = on_event

    async def _emit(self, event: str, data: dict[str, Any] | None = None) -> None:
        if self.on_event is None:
            return
        result = self.on_event(event, data or {})
        if result is not None:
            await result

    async def run(
        self,
        prompt: str,
        *,
        task_id: str | None = None,
        skill_hint: str = "",
        skill_names: list[str] | None = None,
    ) -> ResearchResult:
        started = time.perf_counter()
        settings = self.settings
        await self._emit("thinking", {"phase": "plan", "research": True})

        plan = await build_research_plan(
            self.router, prompt, skill_hint=skill_hint
        )
        # Hint domain from skills if planner missed it
        names = {n.lower() for n in (skill_names or [])}
        if "job-search" in names:
            plan.domain = "jobs"

        run_id = self.store.create_run(
            objective=prompt, task_id=task_id, plan=plan
        )
        await self._emit(
            "plan",
            {
                "research_run_id": run_id,
                "domain": plan.domain,
                "objective": plan.objective,
                "strategies": plan.search_strategies[:8],
            },
        )

        providers = build_search_providers(settings)
        all_queries: list[str] = []
        all_leads = []
        records: list[JobRecord] = []
        raw_record_count = 0
        urls_investigated = 0
        evaluation = None
        incomplete = False
        iteration = 0
        missing: list[str] = []
        next_queries: list[str] = []

        for iteration in range(1, settings.research_max_iterations + 1):
            elapsed = time.perf_counter() - started
            usage = self.router.total_usage()
            if elapsed >= settings.research_max_seconds:
                incomplete = True
                await self._emit(
                    "thinking",
                    {"phase": "budget", "reason": "max_seconds", "elapsed": elapsed},
                )
                break
            if usage.total_tokens >= settings.research_max_tokens:
                incomplete = True
                await self._emit(
                    "thinking",
                    {
                        "phase": "budget",
                        "reason": "max_tokens",
                        "tokens": usage.total_tokens,
                    },
                )
                break

            await self._emit(
                "thinking",
                {"phase": "iterate", "iteration": iteration, "research": True},
            )

            queries = await generate_search_queries(
                self.router,
                plan,
                missing_information=missing,
                next_search_queries=next_queries,
                prior_queries=all_queries,
                iteration=iteration,
            )
            if not queries:
                break
            all_queries.extend(queries)
            self.store.add_queries(
                run_id,
                iteration,
                queries,
                fingerprints=[query_fingerprint(q) for q in queries],
            )
            await self._emit(
                "tool.started",
                {
                    "tool": "research_search",
                    "research": True,
                    "queries": queries,
                    "iteration": iteration,
                },
            )

            leads = await multi_search(
                providers,
                queries,
                max_results_per_query=8,
                max_parallel=settings.research_max_parallel,
            )
            # Prefer unseen URLs
            seen_urls = {lead.canonical_url for lead in all_leads}
            new_leads = [
                lead for lead in leads if lead.canonical_url not in seen_urls
            ]
            all_leads.extend(new_leads)
            self.store.add_leads(run_id, iteration, new_leads)
            await self._emit(
                "tool.finished",
                {
                    "tool": "research_search",
                    "research": True,
                    "leads": len(new_leads),
                    "iteration": iteration,
                },
            )

            remaining_url_budget = max(
                0, settings.research_max_urls - urls_investigated
            )
            batch = new_leads[:remaining_url_budget]
            if not batch and iteration == 1:
                batch = leads[: min(12, settings.research_max_urls)]

            await self._emit(
                "tool.started",
                {
                    "tool": "research_inspect",
                    "research": True,
                    "urls": len(batch),
                    "iteration": iteration,
                },
            )
            snaps = await investigate_leads(
                batch,
                browser=self.browser,
                max_urls=len(batch),
                max_parallel_http=settings.research_max_parallel,
                allow_browser=self.browser is not None,
            )
            urls_investigated += len(snaps)
            await self._emit(
                "tool.finished",
                {
                    "tool": "research_inspect",
                    "research": True,
                    "pages": len(snaps),
                    "iteration": iteration,
                },
            )

            batch_records: list[JobRecord] = []
            for snap in snaps:
                if plan.domain == "jobs":
                    try:
                        record = await extract_job_with_llm(self.router, snap)
                    except Exception:  # noqa: BLE001
                        record = extract_job_from_snapshot(snap)
                else:
                    record = extract_job_from_snapshot(snap)
                    if record is None and snap.text:
                        record = JobRecord(
                            role=snap.title or None,
                            job_url=snap.final_url or snap.url,
                            source_url=snap.url,
                            status="accessible",
                            notes=(snap.text or "")[:400],
                        )
                if record is not None:
                    batch_records.append(record)

            raw_record_count += len(batch_records)
            verified = await verify_records(batch_records)
            records = dedupe_records([*records, *verified])
            self.store.replace_records(run_id, records)

            evaluation = await evaluate_research(
                self.router,
                user_objective=prompt,
                plan=plan,
                queries=all_queries,
                leads=all_leads,
                records=records,
                iteration=iteration,
                max_iterations=settings.research_max_iterations,
            )
            self.store.add_iteration(run_id, iteration, evaluation)
            await self._emit(
                "thinking",
                {
                    "phase": "evaluate",
                    "iteration": iteration,
                    "complete": evaluation.research_complete,
                    "score": evaluation.completion_score,
                    "missing": evaluation.missing_information[:5],
                },
            )

            if evaluation.research_complete:
                incomplete = evaluation.completion_score < 75 and len(
                    [r for r in records if r.status != "closed"]
                ) < 5
                break

            missing = evaluation.missing_information
            next_queries = evaluation.next_search_queries
            incomplete = True
        else:
            incomplete = True

        usage = self.router.total_usage()
        elapsed = time.perf_counter() - started
        metrics = compute_metrics(
            records=records,
            leads=all_leads,
            evaluation=evaluation,
            usage=usage,
            elapsed_seconds=elapsed,
            iterations=iteration,
            queries_run=len(all_queries),
            urls_investigated=urls_investigated,
            raw_record_count=max(raw_record_count, len(records)),
        )

        await self._emit("thinking", {"phase": "synthesize", "research": True})
        result = await synthesize_results(
            self.router,
            user_objective=prompt,
            plan=plan,
            records=records,
            evaluation=evaluation,
            metrics=metrics,
            incomplete=incomplete,
        )

        self.store.update_run(
            run_id,
            status="completed",
            plan=plan,
            evaluation=evaluation,
            metrics=metrics,
            usage={
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
                "estimated_cost_usd": usage.estimated_cost_usd,
                "latency_ms": usage.latency_ms,
            },
            summary=result.summary_markdown,
            incomplete=incomplete,
        )
        await self._emit(
            "done",
            {
                "research": True,
                "run_id": run_id,
                "records": len(result.records),
                "incomplete": incomplete,
                "metrics": metrics.model_dump(),
            },
        )
        return result


async def run_deep_research(
    prompt: str,
    settings: Settings,
    *,
    task_id: str | None = None,
    browser: BrowserSession | None = None,
    skill_hint: str = "",
    skill_names: list[str] | None = None,
    on_event: EventCallback | None = None,
    model: OpenAICompatibleModel | None = None,
) -> ResearchResult:
    router = ModelRouter(settings, model=model)
    orch = ResearchOrchestrator(
        settings,
        router=router,
        browser=browser,
        on_event=on_event,
    )
    return await orch.run(
        prompt,
        task_id=task_id,
        skill_hint=skill_hint,
        skill_names=skill_names,
    )
