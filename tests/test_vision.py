from __future__ import annotations

import struct
import zlib
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ribhus.tools.registry import default_registry
from ribhus.tools.vision import VisionTool, latest_screenshot


def _tiny_png(path: Path, *, rgb: tuple[int, int, int] = (20, 120, 200)) -> Path:
    """Write a valid 8x8 RGB PNG without Pillow."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    w = h = 8
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def test_latest_screenshot(tmp_path: Path):
    shots = tmp_path / "shots"
    _tiny_png(shots / "shot_1.png")
    newer = _tiny_png(shots / "shot_2.png")
    assert latest_screenshot(shots) == newer


def test_vision_registered_when_configured(tmp_path: Path):
    registry = default_registry(
        tmp_path,
        vision_api_key="sk-test",
        vision_base_url="https://api.openai.com/v1",
        vision_model="gpt-4o-mini",
    )
    assert "vision" in registry.names()


def test_vision_not_registered_without_key(tmp_path: Path):
    assert "vision" not in default_registry(tmp_path).names()


@pytest.mark.asyncio
async def test_vision_uses_latest_screenshot(tmp_path: Path):
    shots = tmp_path / ".ribhus" / "screenshots"
    image = _tiny_png(shots / "shot.png")
    tool = VisionTool(
        workspace=tmp_path,
        screenshot_dir=shots,
        api_key="sk-test",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
    )

    fake = AsyncMock()
    fake.chat.completions.create = AsyncMock(
        return_value=type(
            "R",
            (),
            {
                "choices": [
                    type(
                        "C",
                        (),
                        {"message": type("M", (), {"content": "blue square"})()},
                    )()
                ]
            },
        )()
    )

    with patch("ribhus.tools.vision.AsyncOpenAI", return_value=fake):
        result = await tool.execute({"question": "What color?"})

    assert "blue square" in result
    assert "shot.png" in result
    fake.chat.completions.create.assert_awaited_once()
    kwargs = fake.chat.completions.create.await_args.kwargs
    content = kwargs["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert image.exists()


@pytest.mark.asyncio
async def test_vision_missing_image(tmp_path: Path):
    tool = VisionTool(
        workspace=tmp_path,
        screenshot_dir=tmp_path / "empty",
        api_key="sk-test",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
    )
    result = await tool.execute({"question": "What is this?"})
    assert "Error" in result
