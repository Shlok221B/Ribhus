from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import httpx
from openai import AsyncOpenAI

from ribhus.config import Settings
from ribhus.models.base import ModelResponse, ToolCall


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
    ) -> ModelResponse:
        kwargs: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        elif (native := _ollama_chat_url(self.settings.base_url)) is not None:
            # Gemma puts the reply in a reasoning channel on /v1 and leaves
            # content empty. The native API with think disabled returns text.
            ollama = await self._ollama_generate(native, messages, max_tokens)
            if ollama is not None and (ollama.text or "").strip():
                return ollama

        completion = await self.client.chat.completions.create(**kwargs)
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

        return ModelResponse(
            text=message.content,
            tool_calls=tool_calls,
            raw=message,
        )

    async def _ollama_generate(
        self,
        url: str,
        messages: list[dict[str, Any]],
        max_tokens: int | None,
    ) -> ModelResponse | None:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "think": False,
            "stream": False,
        }
        if max_tokens:
            payload["options"] = {"num_predict": max_tokens}
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, json.JSONDecodeError):
            return None
        message = data.get("message") if isinstance(data, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        return ModelResponse(text=content if isinstance(content, str) else "", raw=data)


def _ollama_chat_url(base_url: str) -> str | None:
    parsed = urlparse(base_url or "")
    host = (parsed.hostname or "").lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        return None
    if parsed.port != 11434:
        return None
    scheme = parsed.scheme or "http"
    return f"{scheme}://{parsed.netloc}/api/chat"
