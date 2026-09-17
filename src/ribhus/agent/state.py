from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SYSTEM_PROMPT = """You are Ribhus, an open-source AI agent that gets things done.

You have tools for search, HTTP, files, Python, shell, and a Chromium browser.
Rules:
- Use tools only when they help. Simple questions need no tools.
- For calculations, call `python` once with print(), then give the final answer in plain text.
- After a tool succeeds, do not call the same tool again with the same arguments.
- Browser is already installed. Always use the `browser` tool for web pages.
  Never run `playwright install`, package installs, or other long setup via `terminal`.
- Browser workflow: open → read/extract → (click/type only if needed) → answer.
- Prefer `browser` read/extract over guessing page content. Prefer CSS selectors.
- If `browser` fails, quote the exact error, then fall back to `http_request` or `web_search`.
  Do not invent a vague "technical issue" or ask the user to visit the site themselves.
- High-risk actions (write files, shell, python, browser click/type) may require user approval.
- Skills may be injected below. When a skill is active, follow its workflow and output format.
- When you have enough information, respond with the final answer and STOP calling tools.
- Be concise. Cite URLs when you used web search, HTTP, or browser.
"""


@dataclass
class AgentState:
    messages: list[dict[str, Any]] = field(default_factory=list)
    finished: bool = False
    final_text: str | None = None
    iterations: int = 0

    def add_user(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})

    def add_system(self, content: str) -> None:
        self.messages.insert(0, {"role": "system", "content": content})

    def add_assistant_message(self, message: Any) -> None:
        """Append the raw assistant message object from the OpenAI SDK."""
        payload: dict[str, Any] = {"role": "assistant", "content": message.content}
        if getattr(message, "tool_calls", None):
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in message.tool_calls
            ]
        self.messages.append(payload)

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        self.messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": content,
            }
        )

    def finish(self, text: str | None) -> None:
        self.finished = True
        self.final_text = text or ""
