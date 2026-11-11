from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from openai import AsyncOpenAI

from ribhus.config import Settings
from ribhus.models.base import ModelResponse, TokenUsage, ToolCall

# Rough USD per 1M tokens — used only for estimated_cost_usd logging.
_COST_PER_1M: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "o4-mini": (1.10, 4.40),
    "o3-mini": (1.10, 4.40),
}


def estimate_cost_usd(
    model: str, prompt_tokens: int, completion_tokens: int
) -> float | None:
    key = (model or "").strip().lower()
    rates = _COST_PER_1M.get(key)
    if rates is None:
        for prefix, value in _COST_PER_1M.items():
            if key.startswith(prefix):
                rates = value
                break
    if rates is None:
        return None
    inn, out = rates
    return (prompt_tokens / 1_000_000.0) * inn + (completion_tokens / 1_000_000.0) * out


class OpenAICompatibleModel:
    """Provider-agnostic chat + tools via any OpenAI-compatible endpoint."""

    def __init__(self, settings: Settings) -> None:
        if not settings.api_key:
            raise ValueError(
                "RIBHUS_API_KEY is required. Set it in .env or the environment. "
                "For Ollama, use any non-empty key (e.g. ollama)."
            )
        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
        )

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        *,
        model: str | None = None,
        response_format: dict[str, Any] | None = None,
        operation: str = "",
    ) -> ModelResponse:
        model_id = (model or self.settings.model).strip() or self.settings.model
        kwargs: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if response_format is not None:
            kwargs["response_format"] = response_format
        elif (native := _ollama_chat_url(self.settings.base_url)) is not None and not tools:
            # Gemma puts the reply in a reasoning channel on /v1 and leaves
            # content empty. The native API with think disabled returns text.
            ollama = await self._ollama_generate(
                native, messages, max_tokens, model_id=model_id, operation=operation
            )
            if ollama is not None and (ollama.text or "").strip():
                return ollama

        started = time.perf_counter()
        completion = await self.client.chat.completions.create(**kwargs)
        latency_ms = (time.perf_counter() - started) * 1000.0
        message = completion.choices[0].message

        tool_calls: list[ToolCall] = []
        if message.tool_calls:
            for call in message.tool_calls:
                try:
                    arguments = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {"_raw": call.function.arguments}
                if not isinstance(arguments, dict):
                    arguments = {"value": arguments}
                tool_calls.append(
                    ToolCall(
                        id=call.id,
                        name=call.function.name,
                        arguments=arguments,
                    )
                )

        usage = _usage_from_completion(
            completion,
            model=model_id,
            latency_ms=latency_ms,
            operation=operation,
        )
        return ModelResponse(
            text=message.content,
            tool_calls=tool_calls,
            raw=message,
            usage=usage,
        )

    async def _ollama_generate(
        self,
        url: str,
        messages: list[dict[str, Any]],
        max_tokens: int | None,
        *,
        model_id: str,
        operation: str,
    ) -> ModelResponse | None:
        payload: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "think": False,
            "stream": False,
        }
        if max_tokens:
            payload["options"] = {"num_predict": max_tokens}
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, json.JSONDecodeError):
            return None
        latency_ms = (time.perf_counter() - started) * 1000.0
        message = data.get("message") if isinstance(data, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        return ModelResponse(
            text=content if isinstance(content, str) else "",
            raw=data,
            usage=TokenUsage(
                model=model_id,
                latency_ms=latency_ms,
                operation=operation,
            ),
        )


def _usage_from_completion(
    completion: Any,
    *,
    model: str,
    latency_ms: float,
    operation: str,
) -> TokenUsage:
    raw = getattr(completion, "usage", None)
    prompt = int(getattr(raw, "prompt_tokens", 0) or 0) if raw is not None else 0
    completion_tokens = (
        int(getattr(raw, "completion_tokens", 0) or 0) if raw is not None else 0
    )
    total = int(getattr(raw, "total_tokens", 0) or 0) if raw is not None else 0
    if total <= 0:
        total = prompt + completion_tokens
    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion_tokens,
        total_tokens=total,
        model=model,
        latency_ms=latency_ms,
        estimated_cost_usd=estimate_cost_usd(model, prompt, completion_tokens),
        operation=operation,
    )


def _ollama_chat_url(base_url: str) -> str | None:
    parsed = urlparse(base_url or "")
    host = (parsed.hostname or "").lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        return None
    if parsed.port != 11434:
        return None
    scheme = parsed.scheme or "http"
    return f"{scheme}://{parsed.netloc}/api/chat"
