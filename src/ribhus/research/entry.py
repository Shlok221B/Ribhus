"""Shared entry helper for CLI / dashboard / bots."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ribhus.config import Settings
from ribhus.models.openai_compatible import OpenAICompatibleModel
from ribhus.research.loop import run_deep_research, should_run_research
from ribhus.tools.browser import BrowserSession

EventCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]


async def maybe_run_deep_research(
    prompt: str,
    settings: Settings,
    *,
    skill_names: list[str],
    skill_hint: str = "",
    browser: BrowserSession | None = None,
    task_id: str | None = None,
    on_event: EventCallback | None = None,
    model: OpenAICompatibleModel | None = None,
) -> str | None:
    """Return research markdown if this prompt should use the orchestrator."""
    if not should_run_research(
        prompt, settings=settings, skill_names=skill_names
    ):
        return None
    result = await run_deep_research(
        prompt,
        settings,
        task_id=task_id,
        browser=browser,
        skill_hint=skill_hint,
        skill_names=skill_names,
        on_event=on_event,
        model=model,
    )
    return (result.summary_markdown or "").strip() or None
