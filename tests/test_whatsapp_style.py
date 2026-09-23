"""Tests for global WhatsApp writing-style learning."""

from __future__ import annotations

from pathlib import Path

import pytest

from ribhus.channels.whatsapp_web.style_profile import (
    WHATSAPP_STYLE_KEY,
    extract_outgoing_style,
    format_style_hint,
    merge_style,
)
from ribhus.memory.extract import PINNED_KEYS
from ribhus.memory.service import MemoryService


def test_whatsapp_style_in_pinned_keys():
    assert "whatsapp_style" in PINNED_KEYS
    assert WHATSAPP_STYLE_KEY == "whatsapp_style"


def test_extract_via_meta_self_name():
    messages = [
        {
            "direction": "in",  # mis-tagged by DOM
            "outgoing": False,
            "text": "haan aa raha yaar",
            "meta": "[10:42 pm, 23/09/2026] Shlok: ",
        },
        {"direction": "in", "text": "ok", "meta": "[10:43 pm, 23/09/2026] Guptaji: "},
    ]
    snap = extract_outgoing_style(messages, self_names=["Shlok"])
    assert snap is not None
    assert snap.message_count == 1
    assert "yaar" in snap.samples[0].lower() or "haan" in snap.samples[0].lower()


def test_extract_outgoing_only_ignores_incoming():
    messages = [
        {"direction": "in", "text": "Arre theeke yaar kab aa raha"},
        {"direction": "out", "text": "haan bhai 10 min"},
        {"direction": "out", "text": "ok done"},
        {"direction": "in", "text": "cool"},
        {"direction": "out", "text": "[Ribhus] ignore me"},
    ]
    snap = extract_outgoing_style(messages)
    assert snap is not None
    assert snap.message_count == 2
    assert snap.register == "hinglish"
    assert any("bhai" in p or "haan" in p for p in snap.signature_phrases) or snap.samples
    assert all("[Ribhus]" not in s for s in snap.samples)


def test_extract_returns_none_without_outgoing():
    assert extract_outgoing_style([{"direction": "in", "text": "hi"}]) is None


def test_merge_style_preserves_prior_phrases():
    first = extract_outgoing_style(
        [
            {"direction": "out", "text": "yaar kal milte"},
            {"direction": "out", "text": "theeke bro"},
        ]
    )
    assert first is not None
    profile = merge_style(None, first)
    assert "Register:" in profile
    assert "Samples:" in profile

    second = extract_outgoing_style(
        [
            {"direction": "out", "text": "ok pakka"},
            {"direction": "out", "text": "scene set"},
        ]
    )
    assert second is not None
    merged = merge_style(profile, second)
    assert "yaar" in merged.lower() or "theeke" in merged.lower() or "bhai" in merged.lower() or "pakka" in merged.lower()
    assert "From ~" in merged
    hint = format_style_hint(merged)
    assert hint.startswith("Your writing style")


def test_learn_whatsapp_style_persists(tmp_path: Path):
    memory = MemoryService.from_path(tmp_path / "memory.sqlite")
    msgs = [
        {"direction": "in", "text": "kahan hai"},
        {"direction": "out", "text": "aa raha yaar"},
        {"direction": "out", "text": "5 min bas"},
    ]
    updated = memory.learn_whatsapp_style(msgs)
    assert updated is not None
    assert "WhatsApp writing style" in updated
    got = memory.get_whatsapp_style()
    assert got is not None
    assert "yaar" in got.lower() or "bas" in got.lower() or "Samples:" in got

    # Second learn merges
    again = memory.learn_whatsapp_style(
        [{"direction": "out", "text": "haan theeke"}]
    )
    assert again is not None
    assert memory.get_whatsapp_style() == again
    memory.close()


def test_learn_skipped_when_memory_disabled(tmp_path: Path):
    memory = MemoryService.from_path(tmp_path / "memory.sqlite", env_enabled=False)
    assert (
        memory.learn_whatsapp_style([{"direction": "out", "text": "hi yaar"}])
        is None
    )
    memory.close()


@pytest.mark.asyncio
async def test_whatsapp_reply_reclassifies_shlok_meta():
    from ribhus.channels.whatsapp_web.policy import WhatsAppPolicy
    from ribhus.channels.whatsapp_web.tools import WhatsAppReplyTool

    class FakeNav:
        async def open_chat(self, name: str) -> str:
            return name

        async def main_open(self) -> bool:
            return True

        async def current_title(self) -> str:
            return "Hitika Shah"

    class FakeReader:
        last_debug: dict = {}

        async def read_messages(self, limit: int = 15):
            # Real audit shape: Shlok's bubbles tagged direction=in
            return [
                {
                    "direction": "in",
                    "text": "Kya krr rhi ho",
                    "meta": "[10:48 PM, 9/23/2026] Shlok:",
                },
                {
                    "direction": "in",
                    "text": "Barobar",
                    "meta": "[10:49 PM, 9/23/2026] Hitika Shah:",
                },
            ]

        @staticmethod
        def format(messages, *, title=None, debug=None, include_register=False):
            lines = [f"Chat: {title}"]
            for m in messages:
                who = "You" if m.get("direction") == "out" else "Them"
                lines.append(f"{who}: {m.get('text')}")
            return "\n".join(lines)

    class FakeMemory:
        enabled = True

        def _self_names_for_style(self):
            return ["Shlok"]

        def learn_whatsapp_style(self, messages):
            outs = [m for m in messages if m.get("direction") == "out"]
            assert len(outs) == 1
            assert outs[0]["text"] == "Kya krr rhi ho"
            return (
                "WhatsApp writing style (you — global):\n"
                "Register: hinglish\nSamples:\n- Kya krr rhi ho"
            )

    tool = WhatsAppReplyTool(
        FakeNav(),
        FakeReader(),
        WhatsAppPolicy(cooldown_seconds=0),
        memory=FakeMemory(),
    )
    result = await tool.execute({"contact": "Hitika Shah"})
    assert "You: Kya krr rhi ho" in result
    assert "Them: Barobar" in result
    assert "Your writing style" in result


@pytest.mark.asyncio
async def test_whatsapp_reply_learns_style():
    from ribhus.channels.whatsapp_web.policy import WhatsAppPolicy
    from ribhus.channels.whatsapp_web.tools import WhatsAppReplyTool

    class FakeNav:
        async def open_chat(self, name: str) -> str:
            return name

        async def main_open(self) -> bool:
            return True

        async def current_title(self) -> str:
            return "Guptaji"

    class FakeReader:
        last_debug: dict = {}

        async def read_messages(self, limit: int = 15):
            return [
                {"direction": "in", "text": "kya scene"},
                {"direction": "out", "text": "sab theeke yaar"},
            ]

        @staticmethod
        def format(messages, *, title=None, debug=None, include_register=False):
            return f"Chat: {title}\nYou: sab theeke yaar"

    class FakeMemory:
        enabled = True
        learned = None

        def _self_names_for_style(self):
            return []

        def learn_whatsapp_style(self, messages):
            self.learned = messages
            return (
                "WhatsApp writing style (you — global):\n"
                "Register: hinglish\nSamples:\n- sab theeke yaar"
            )

        def get_whatsapp_style(self):
            return None

    mem = FakeMemory()
    tool = WhatsAppReplyTool(
        FakeNav(), FakeReader(), WhatsAppPolicy(cooldown_seconds=0), memory=mem
    )
    result = await tool.execute({"contact": "Guptaji"})
    assert mem.learned is not None
    assert "Your writing style" in result
    assert "YOUR saved writing style" in result
