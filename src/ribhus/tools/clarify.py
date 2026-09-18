from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ribhus.policy.levels import RiskLevel
from ribhus.tools.base import Tool

# (question, choices) -> user's answer text
ClarifyAsker = Callable[[str, list[str] | None], Awaitable[str] | str]


class ClarifyTool(Tool):
    name = "clarify"
    description = (
        "Ask the user one precise clarifying question mid-task when a detail "
        "would change the result. Be specific — not 'any preferences?' but "
        "e.g. 'Which area of Goa: North (Baga/Calangute), South (Palolem/Colva), "
        "or Panaji?', or budget bands, or exact dates. Prefer numbered local "
        "choices. Do not guess area, budget, dates, company, or contact when "
        "clarify is available. After the user answers, continue the task."
    )
    risk_level = RiskLevel.LOW.value

    def __init__(self, asker: ClarifyAsker | None = None) -> None:
        self.asker = asker

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": (
                        "One precise question. Name the place/constraint. "
                        "Bad: 'Any preferences?'. "
                        "Good: 'Which part of Goa — North Goa (Baga/Calangute), "
                        "South Goa (Palolem), or Panaji?'"
                    ),
                },
                "choices": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "2–6 concrete choices with local names when useful "
                        "(areas, budget bands, date options)"
                    ),
                },
                "allow_free_text": {
                    "type": "boolean",
                    "description": "If true (default), user may type a custom answer",
                    "default": True,
                },
            },
            "required": ["question"],
        }

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        if self.asker is None:
            return (
                "Error: clarify needs an interactive CLI session. "
                "State a reasonable assumption in your answer instead, "
                "or ask the user in plain text and stop."
            )
        question = str(arguments.get("question") or "").strip()
        if not question:
            return "Error: question is required"
        return None

    async def execute(self, arguments: dict[str, Any]) -> str:
        if self.asker is None:
            return (
                "Error: clarify needs an interactive CLI session. "
                "State a reasonable assumption instead."
            )
        question = str(arguments.get("question") or "").strip()
        if not question:
            return "Error: question is required"

        raw_choices = arguments.get("choices")
        choices: list[str] | None = None
        if isinstance(raw_choices, list):
            cleaned = [str(c).strip() for c in raw_choices if str(c).strip()]
            if cleaned:
                choices = cleaned[:8]

        allow_free = arguments.get("allow_free_text")
        if allow_free is False and not choices:
            return "Error: choices are required when allow_free_text is false"

        # Stash for askers that want to know free-text policy
        if isinstance(arguments, dict):
            arguments["_allow_free_text"] = allow_free is not False

        result = self.asker(question, choices)
        if isinstance(result, Awaitable):
            answer = await result
        else:
            answer = result

        answer = str(answer or "").strip()
        if not answer:
            return "User did not answer (empty). Ask once more or state an assumption."
        if answer.lower() in {"cancel", "/cancel", "skip", "/skip"}:
            return (
                "User skipped the question. Continue with a clearly stated "
                "assumption, or stop if the task cannot proceed."
            )
        if choices and answer.isdigit():
            idx = int(answer)
            if 1 <= idx <= len(choices):
                answer = choices[idx - 1]
        return f"User answered: {answer}"
