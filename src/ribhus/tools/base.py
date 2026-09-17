from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from ribhus.policy.levels import RiskLevel


class Tool(ABC):
    name: str
    description: str
    risk_level: str = RiskLevel.LOW.value

    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema for tool arguments."""

    @abstractmethod
    async def execute(self, arguments: dict[str, Any]) -> str:
        """Run the tool and return a string observation for the model."""

    def risk_for_arguments(self, arguments: dict[str, Any]) -> RiskLevel:
        """Override for tools whose risk depends on the action (e.g. browser)."""
        return RiskLevel.parse(self.risk_level)

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema(),
            },
        }


class ToolResult(BaseModel):
    name: str
    content: str
    ok: bool = True
    error: str | None = None
