from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    latency_ms: float = 0.0
    estimated_cost_usd: float | None = None
    operation: str = ""

    def add(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            model=self.model or other.model,
            latency_ms=self.latency_ms + other.latency_ms,
            estimated_cost_usd=(
                None
                if self.estimated_cost_usd is None and other.estimated_cost_usd is None
                else (self.estimated_cost_usd or 0.0) + (other.estimated_cost_usd or 0.0)
            ),
            operation=self.operation or other.operation,
        )


@dataclass
class ModelResponse:
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None
    usage: TokenUsage | None = None

    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)
