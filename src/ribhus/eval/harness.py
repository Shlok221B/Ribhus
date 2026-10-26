"""Shared FakeModel, stubs, and workspace helpers for hermetic evals."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ribhus.models.base import ModelResponse, ToolCall
from ribhus.tools.base import Tool


def repo_root() -> Path | None:
    """Best-effort checkout root (pyproject.toml). None when running from a wheel."""
    here = Path(__file__).resolve()
    for start in (Path.cwd(), *here.parents):
        if (start / "pyproject.toml").is_file() and (start / "src" / "ribhus").is_dir():
            return start
    return None


def bundled_skill(name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "skills" / "bundled" / name


@contextmanager
def temp_workspace() -> Iterator[Path]:
    path = Path(tempfile.mkdtemp(prefix="ribhus-eval-"))
    (path / ".ribhus").mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@contextmanager
def isolated_cwd(path: Path) -> Iterator[None]:
    old = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


class FakeRawMessage:
    def __init__(self, content: str | None, tool_calls: list | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class FakeFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class FakeToolCallObj:
    def __init__(self, id: str, name: str, arguments: str) -> None:
        self.id = id
        self.function = FakeFunction(name, arguments)


class FakeModel:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = list(responses)
        self.calls = 0

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelResponse:
        self.calls += 1
        if not self.responses:
            return ModelResponse(text="fallback")
        return self.responses.pop(0)


def tool_response(call_id: str, name: str, arguments: dict[str, Any]) -> ModelResponse:
    payload = json.dumps(arguments)
    raw = FakeRawMessage(None, [FakeToolCallObj(call_id, name, payload)])
    return ModelResponse(
        text=None,
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
        raw=raw,
    )


def text_response(text: str) -> ModelResponse:
    return ModelResponse(text=text, tool_calls=[], raw=FakeRawMessage(text))


class EchoTool(Tool):
    name = "echo"
    description = "Echo text"
    risk_level = "low"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

    async def execute(self, arguments: dict[str, Any]) -> str:
        return str(arguments.get("text", ""))


class ForceApprovalStub(Tool):
    """Minimal send-shaped tool with force_approval (no browser)."""

    risk_level = "high"
    force_approval = True
    description = "Stub send tool that always requires approval"

    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"Stub {name} that always requires approval"
        self.sent: list[dict[str, Any]] = []

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"body": {"type": "string"}}}

    async def execute(self, arguments: dict[str, Any]) -> str:
        self.sent.append(arguments)
        return f"Sent: {arguments}"


def user_contents(state: Any) -> list[str]:
    return [
        str(m.get("content") or "")
        for m in state.messages
        if m.get("role") == "user"
    ]
