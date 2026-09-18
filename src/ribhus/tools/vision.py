from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from ribhus.policy.levels import RiskLevel
from ribhus.tools.base import Tool
from ribhus.tools.filesystem import _resolve_path

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_MAX_BYTES = 8_000_000


def latest_screenshot(screenshot_dir: Path) -> Path | None:
    if not screenshot_dir.exists():
        return None
    shots = [
        p
        for p in screenshot_dir.iterdir()
        if p.is_file() and p.suffix.lower() in _IMAGE_SUFFIXES
    ]
    if not shots:
        return None
    return max(shots, key=lambda p: p.stat().st_mtime)


async def analyze_image(
    *,
    image_path: Path,
    question: str,
    api_key: str,
    base_url: str,
    model: str,
    max_tokens: int = 1024,
) -> str:
    """Ask a vision-capable chat model about an image file."""
    if not api_key:
        return "Error: RIBHUS_API_KEY is required for vision"
    if not image_path.exists() or not image_path.is_file():
        return f"Error: image not found: {image_path}"
    size = image_path.stat().st_size
    if size > _MAX_BYTES:
        return f"Error: image too large ({size} bytes > {_MAX_BYTES})"
    if image_path.suffix.lower() not in _IMAGE_SUFFIXES:
        return (
            f"Error: unsupported image type '{image_path.suffix}'. "
            f"Use one of: {', '.join(sorted(_IMAGE_SUFFIXES))}"
        )

    mime = mimetypes.guess_type(str(image_path))[0] or "image/png"
    data = base64.standard_b64encode(image_path.read_bytes()).decode("ascii")
    data_url = f"data:{mime};base64,{data}"

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    try:
        completion = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question.strip()},
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                    ],
                }
            ],
            max_tokens=max_tokens,
        )
    except Exception as exc:  # noqa: BLE001
        return f"Error from vision model: {exc}"

    text = completion.choices[0].message.content
    if not text or not str(text).strip():
        return "Error: vision model returned empty content"
    return str(text).strip()


class VisionTool(Tool):
    name = "vision"
    description = (
        "Ask a question about an image (screenshot, receipt, QR, UI). "
        "Provide path to a workspace image, or omit path to use the latest "
        "browser screenshot under .ribhus/screenshots. "
        "Typical flow: browser action=screenshot (or screenshot_ask), then vision. "
        "Requires a vision-capable model (e.g. gpt-4o-mini)."
    )
    risk_level = RiskLevel.MEDIUM.value

    def __init__(
        self,
        workspace: Path,
        screenshot_dir: Path,
        *,
        api_key: str,
        base_url: str,
        model: str,
    ) -> None:
        self.workspace = workspace
        self.screenshot_dir = screenshot_dir
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": (
                        "What to look for or describe "
                        "(e.g. 'What is the score?', 'Read the QR context', "
                        "'Summarize this receipt in ₹')"
                    ),
                },
                "path": {
                    "type": "string",
                    "description": (
                        "Image path relative to workspace (png/jpg/webp/gif). "
                        "Omit to use the latest .ribhus/screenshots shot."
                    ),
                },
            },
            "required": ["question"],
        }

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        question = str(arguments.get("question") or "").strip()
        if not question:
            return "Error: question is required"
        return None

    async def execute(self, arguments: dict[str, Any]) -> str:
        question = str(arguments.get("question") or "").strip()
        path_str = str(arguments.get("path") or "").strip()

        if path_str:
            try:
                image_path = _resolve_path(self.workspace, path_str)
            except PermissionError as exc:
                return f"Error: {exc}"
        else:
            image_path = latest_screenshot(self.screenshot_dir)
            if image_path is None:
                return (
                    "Error: no path given and no screenshots found in "
                    f"{self.screenshot_dir}. Take one with browser "
                    "action=screenshot first."
                )

        answer = await analyze_image(
            image_path=image_path,
            question=question,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
        )
        return f"Image: {image_path}\n\n{answer}"
