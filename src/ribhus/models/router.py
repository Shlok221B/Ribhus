"""Configurable multi-model routing for research operations."""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from ribhus.config import Settings
from ribhus.models.base import ModelResponse, TokenUsage
from ribhus.models.openai_compatible import OpenAICompatibleModel

logger = logging.getLogger(__name__)

ResearchOperation = Literal[
    "plan",
    "query_gen",
    "extract",
    "classify",
    "evaluate",
    "synthesize",
]

_REASONING_OPS: frozenset[str] = frozenset({"plan", "evaluate", "synthesize"})


class ModelRouter:
    """Route research LLM calls by operation; track usage; fall back on failure."""

    def __init__(
        self,
        settings: Settings,
        model: OpenAICompatibleModel | None = None,
    ) -> None:
        self.settings = settings
        self.model = model or OpenAICompatibleModel(settings)
        self.usage_log: list[TokenUsage] = []

    def model_for(self, operation: ResearchOperation) -> tuple[str, str]:
        """Return (primary, fallback) model ids for an operation."""
        if operation in _REASONING_OPS:
            return (
                self.settings.effective_reasoning_model,
                self.settings.effective_reasoning_fallback,
            )
        return (
            self.settings.effective_fast_model,
            self.settings.effective_fast_fallback,
        )

    def total_usage(self) -> TokenUsage:
        total = TokenUsage(operation="research_total")
        for item in self.usage_log:
            total = total.add(item)
        return total

    async def complete(
        self,
        operation: ResearchOperation,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int | None = None,
        json_schema: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelResponse:
        primary, fallback = self.model_for(operation)
        response_format = None
        if json_schema is not None:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": f"ribhus_{operation}",
                    "strict": False,
                    "schema": json_schema,
                },
            }
        try:
            response = await self.model.generate(
                messages,
                tools=tools,
                max_tokens=max_tokens,
                model=primary,
                response_format=response_format,
                operation=operation,
            )
        except Exception as primary_err:  # noqa: BLE001
            if not fallback or fallback == primary:
                raise
            logger.warning(
                "Model %s failed for %s (%s); falling back to %s",
                primary,
                operation,
                primary_err,
                fallback,
            )
            response = await self.model.generate(
                messages,
                tools=tools,
                max_tokens=max_tokens,
                model=fallback,
                response_format=response_format,
                operation=operation,
            )

        if response.usage is not None:
            self.usage_log.append(response.usage)
        return response

    async def complete_json(
        self,
        operation: ResearchOperation,
        messages: list[dict[str, Any]],
        *,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Complete and parse JSON (schema-guided when the API supports it)."""
        # Prefer json_object when no schema — more portable across providers.
        response_format: dict[str, Any] | None
        if json_schema is not None:
            try:
                response = await self.complete(
                    operation,
                    messages,
                    max_tokens=max_tokens,
                    json_schema=json_schema,
                )
            except Exception:  # noqa: BLE001 — schema mode unsupported
                response_format = {"type": "json_object"}
                primary, fallback = self.model_for(operation)
                try:
                    response = await self.model.generate(
                        messages,
                        max_tokens=max_tokens,
                        model=primary,
                        response_format=response_format,
                        operation=operation,
                    )
                except Exception:
                    response = await self.model.generate(
                        messages,
                        max_tokens=max_tokens,
                        model=fallback,
                        response_format=response_format,
                        operation=operation,
                    )
                if response.usage is not None:
                    self.usage_log.append(response.usage)
        else:
            response = await self.complete(
                operation,
                [
                    *messages[:-1],
                    {
                        **messages[-1],
                        "content": (
                            str(messages[-1].get("content") or "")
                            + "\n\nRespond with valid JSON only."
                        ),
                    },
                ]
                if messages
                else messages,
                max_tokens=max_tokens,
            )
            # Force json_object for non-schema path via retry if needed
            if not (response.text or "").strip().startswith("{"):
                primary, _ = self.model_for(operation)
                response = await self.model.generate(
                    messages,
                    max_tokens=max_tokens,
                    model=primary,
                    response_format={"type": "json_object"},
                    operation=operation,
                )
                if response.usage is not None:
                    self.usage_log.append(response.usage)

        return _parse_json_object(response.text or "")


def _parse_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}
