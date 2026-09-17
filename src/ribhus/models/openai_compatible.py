from __future__ import annotations

import json
from typing import Any

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
    ) -> ModelResponse:
        kwargs: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

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
