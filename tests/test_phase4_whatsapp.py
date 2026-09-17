from __future__ import annotations

from pathlib import Path

import pytest

from ribhus.channels.whatsapp_web.navigator import (
    ChatNotFound,
    is_chrome_label,
    names_match,
    pick_matching_name,
)
from ribhus.channels.whatsapp_web.policy import (
    WhatsAppKilled,
    WhatsAppPolicy,
    WhatsAppPolicyError,
)
from ribhus.channels.whatsapp_web.reader import WhatsAppReader
from ribhus.channels.whatsapp_web.session import WhatsAppSession
from ribhus.channels.whatsapp_web.tools import (
    WhatsAppOpenChatTool,
    WhatsAppReadTool,
    WhatsAppSendTool,
    WhatsAppStatusTool,
)
from ribhus.cli.main import _whatsapp_send_approver
from ribhus.policy.engine import PolicyEngine
from ribhus.policy.levels import RiskLevel
from ribhus.tools.browser import BrowserSession, DomainNotAllowed
from ribhus.tools.filesystem import WriteFileTool
from ribhus.tools.registry import ToolRegistry, default_registry


def test_names_match_loose():
    assert names_match("Rahul", "rahul")
    assert names_match("Rahul 👋", "Rahul")
    assert names_match("Priya Sharma", "priya")
    assert names_match("Gupta ji", "Guptaji")
    assert names_match("Guptaji", "Gupta Ji")
    assert not names_match("Rahul", "Ananya")
    assert not names_match(None, "Rahul")


def test_pick_matching_name_prefers_exact():
    names = ["Gupta", "Guptaji", "Gupta Builders"]
    assert pick_matching_name(names, "Guptaji") == "Guptaji"
    assert pick_matching_name(["Gupta ji", "Rahul"], "Guptaji") == "Gupta ji"
    assert pick_matching_name(["Rahul", "Priya"], "Guptaji") is None


def test_profile_details_is_chrome_not_a_chat():
    assert is_chrome_label("Profile details")
    assert is_chrome_label("Contact info")
    assert not is_chrome_label("Guptaji")
    assert pick_matching_name(["Profile details", "Guptaji"], "Guptaji") == "Guptaji"
    assert not names_match("Profile details", "Guptaji")


def test_kill_switch_persists(tmp_path: Path):
    path = tmp_path / "whatsapp.killed"
    policy = WhatsAppPolicy(kill_path=path, cooldown_seconds=0)
    assert not policy.is_killed()
    policy.kill()
    assert path.exists()
    other = WhatsAppPolicy(kill_path=path, cooldown_seconds=0)
    assert other.is_killed()
    with pytest.raises(WhatsAppKilled):
        other.assert_can_send("Rahul", "hi")
    other.resume()
    assert not path.exists()
    assert not other.is_killed()


def test_disabled_env_is_killed():
    policy = WhatsAppPolicy(enabled=False, cooldown_seconds=0)
    assert policy.is_killed()
    with pytest.raises(WhatsAppKilled):
        policy.assert_alive()


def test_refuse_bulk_and_empty():
    policy = WhatsAppPolicy(cooldown_seconds=0)
    assert "Bulk" in (policy.refuse_reason("Rahul, Priya", "hi") or "")
    assert "Bulk" in (policy.refuse_reason(["Rahul", "Priya"], "hi") or "")
    assert "Broadcast" in (policy.refuse_reason("broadcast", "hi") or "")
    assert "empty" in (policy.refuse_reason("Rahul", "  ") or "").lower()
    assert policy.refuse_reason("Rahul", "On my way") is None


def test_rate_limit_and_cooldown():
    policy = WhatsAppPolicy(
        cooldown_seconds=0,
        sends_per_minute=1,
        sends_per_hour=10,
    )
    policy.record_send("Rahul", "one")
    reason = policy.refuse_reason("Priya", "two")
    assert reason and "per minute" in reason

    policy = WhatsAppPolicy(cooldown_seconds=30, sends_per_minute=10, sends_per_hour=10)
    policy.record_send("Rahul", "one")
    reason = policy.refuse_reason("Rahul", "two")
    assert reason and "Cooldown" in reason


def test_identical_message_spam():
    policy = WhatsAppPolicy(
        cooldown_seconds=0,
        sends_per_minute=10,
        sends_per_hour=10,
        max_identical_contacts=2,
    )
    blast = "Buy now!!!"
    policy.record_send("A", blast)
    policy.record_send("B", blast)
    reason = policy.refuse_reason("C", blast)
    assert reason and "spam" in reason.lower()
    assert policy.refuse_reason("A", blast) is None  # same contact is ok


def test_hour_cap():
    policy = WhatsAppPolicy(cooldown_seconds=0, sends_per_minute=50, sends_per_hour=2)
    policy.record_send("A", "one")
    policy.record_send("B", "two")
    reason = policy.refuse_reason("C", "three")
    assert reason and "per hour" in reason


@pytest.mark.asyncio
async def test_force_approval_ignores_auto_approve():
    tool = WhatsAppSendTool(
        navigator=_FakeNavigator(),
        sender=_FakeSender(),
        policy=WhatsAppPolicy(cooldown_seconds=0),
    )
    assert tool.force_approval is True

    blocked = PolicyEngine(auto_approve=True, approver=None)
    allowed, msg = await blocked.authorize(tool, {"contact": "Rahul", "message": "hi"})
    assert not allowed
    assert msg and "cannot be auto-approved" in msg

    ok = PolicyEngine(auto_approve=True, approver=lambda n, r, a: True)
    allowed, msg = await ok.authorize(tool, {"contact": "Rahul", "message": "hi"})
    assert allowed
    assert msg is None


@pytest.mark.asyncio
async def test_auto_approve_still_skips_normal_high_risk():
    policy = PolicyEngine(auto_approve=True, approve_at_or_above=RiskLevel.HIGH)
    tool = WriteFileTool(workspace=Path("."))
    tool.risk_level = RiskLevel.HIGH.value
    allowed, msg = await policy.authorize(tool, {"path": "x", "content": "y"})
    assert allowed
    assert msg is None


@pytest.mark.asyncio
async def test_send_denied_never_types():
    sender = _FakeSender()
    nav = _FakeNavigator()
    tool = WhatsAppSendTool(
        navigator=nav,
        sender=sender,
        policy=WhatsAppPolicy(cooldown_seconds=0),
    )
    registry = ToolRegistry(
        policy=PolicyEngine(auto_approve=True, approver=lambda n, r, a: False)
    )
    registry.register(tool)
    result = await registry.execute(
        "whatsapp_send", {"contact": "Rahul", "message": "hi there"}
    )
    assert "denied" in result.lower() or "Denied" in result
    assert sender.sent == []
    assert nav.opened is None


@pytest.mark.asyncio
async def test_send_blocked_by_kill_switch_skips_approval(tmp_path: Path):
    sender = _FakeSender()
    policy = WhatsAppPolicy(kill_path=tmp_path / "killed", cooldown_seconds=0)
    tool = WhatsAppSendTool(
        navigator=_FakeNavigator(),
        sender=sender,
        policy=policy,
    )
    called: list[int] = []

    def approver(name, risk, arguments):
        called.append(1)
        return True

    registry = ToolRegistry(policy=PolicyEngine(auto_approve=True, approver=approver))
    registry.register(tool)
    policy.kill()
    result = await registry.execute(
        "whatsapp_send", {"contact": "Rahul", "message": "hi"}
    )
    assert "Error" in result
    assert called == []
    assert sender.sent == []


@pytest.mark.asyncio
async def test_send_bulk_skips_approval():
    sender = _FakeSender()
    tool = WhatsAppSendTool(
        navigator=_FakeNavigator(),
        sender=sender,
        policy=WhatsAppPolicy(cooldown_seconds=0),
    )
    called: list[int] = []

    def approver(name, risk, arguments):
        called.append(1)
        return True

    registry = ToolRegistry(policy=PolicyEngine(auto_approve=True, approver=approver))
    registry.register(tool)
    result = await registry.execute(
        "whatsapp_send", {"contact": "Rahul, Priya", "message": "hi"}
    )
    assert "Error" in result
    assert "Bulk" in result
    assert called == []
    assert sender.sent == []


@pytest.mark.asyncio
async def test_send_refuses_chat_mismatch():
    sender = _FakeSender()
    nav = _FakeNavigator()
    nav.force_title = "Someone Else"
    tool = WhatsAppSendTool(
        navigator=nav,
        sender=sender,
        policy=WhatsAppPolicy(cooldown_seconds=0),
    )
    result = await tool.execute({"contact": "Rahul", "message": "hi"})
    assert "Refusing" in result
    assert sender.sent == []


@pytest.mark.asyncio
async def test_send_failure_clears_and_does_not_record():
    class Boom(_FakeSender):
        async def send(self, text: str) -> None:
            raise RuntimeError("network")

    sender = Boom()
    policy = WhatsAppPolicy(cooldown_seconds=0)
    tool = WhatsAppSendTool(_FakeNavigator(), sender, policy)
    result = await tool.execute({"contact": "Rahul", "message": "hi"})
    assert result.startswith("Error")
    assert sender.cleared == 1
    assert policy._sends == []


@pytest.mark.asyncio
async def test_send_happy_path_records():
    sender = _FakeSender()
    policy = WhatsAppPolicy(cooldown_seconds=0)
    tool = WhatsAppSendTool(
        navigator=_FakeNavigator(),
        sender=sender,
        policy=policy,
    )
    registry = ToolRegistry(
        policy=PolicyEngine(auto_approve=True, approver=lambda n, r, a: True)
    )
    registry.register(tool)
    result = await registry.execute(
        "whatsapp_send", {"contact": "Rahul", "message": "see you at 6"}
    )
    assert result.startswith("Sent")
    assert sender.sent == ["see you at 6"]
    assert len(policy._sends) == 1


@pytest.mark.asyncio
async def test_send_edit_uses_new_text():
    sender = _FakeSender()
    tool = WhatsAppSendTool(
        navigator=_FakeNavigator(),
        sender=sender,
        policy=WhatsAppPolicy(cooldown_seconds=0),
    )

    def approve_and_edit(name, risk, arguments):
        arguments["message"] = "edited draft"
        return True

    registry = ToolRegistry(
        policy=PolicyEngine(auto_approve=True, approver=approve_and_edit)
    )
    registry.register(tool)
    result = await registry.execute(
        "whatsapp_send", {"contact": "Rahul", "message": "original"}
    )
    assert "Sent" in result
    assert sender.sent == ["edited draft"]


@pytest.mark.asyncio
async def test_open_and_read_killed():
    policy = WhatsAppPolicy(enabled=False)
    open_tool = WhatsAppOpenChatTool(_FakeNavigator(), policy)
    read_tool = WhatsAppReadTool(_FakeNavigator(), _FakeReader(), policy)
    opened = await open_tool.execute({"contact": "Rahul"})
    read = await read_tool.execute({"contact": "Rahul"})
    assert opened.startswith("Error")
    assert read.startswith("Error")


@pytest.mark.asyncio
async def test_read_formats_messages():
    nav = _FakeNavigator()
    reader = _FakeReader()
    tool = WhatsAppReadTool(nav, reader, WhatsAppPolicy(cooldown_seconds=0))
    result = await tool.execute({"contact": "Rahul", "limit": 5})
    assert "Chat: Rahul" in result
    assert "Them: Are you coming?" in result
    assert "You: On my way" in result


@pytest.mark.asyncio
async def test_status_does_not_need_browser(tmp_path: Path):
    session = WhatsAppSession(user_data_dir=tmp_path / "profile")
    policy = WhatsAppPolicy(kill_path=tmp_path / "killed")
    tool = WhatsAppStatusTool(session, policy)
    text = await tool.execute({})
    assert "not the official" in text.lower() or "WhatsApp Web" in text
    assert "killed=False" in text
    assert session.page is None


def test_browser_cannot_open_whatsapp(tmp_path: Path):
    session = BrowserSession(user_data_dir=tmp_path / "profile")
    with pytest.raises(DomainNotAllowed, match="WhatsApp"):
        session.check_url("https://web.whatsapp.com")
    with pytest.raises(DomainNotAllowed, match="WhatsApp"):
        session.check_url("https://api.whatsapp.com/send")


def test_default_registry_includes_whatsapp(tmp_path: Path):
    session = WhatsAppSession(user_data_dir=tmp_path / "wa")
    policy = WhatsAppPolicy(kill_path=tmp_path / "killed")
    registry = default_registry(
        tmp_path, whatsapp_session=session, whatsapp_policy=policy
    )
    names = registry.names()
    assert "whatsapp_status" in names
    assert "whatsapp_open_chat" in names
    assert "whatsapp_read" in names
    assert "whatsapp_send" in names
    send = registry.get("whatsapp_send")
    assert send is not None
    assert send.force_approval is True
    assert send.risk_level == RiskLevel.MEDIUM.value


def test_default_registry_without_whatsapp_unchanged(tmp_path: Path):
    names = default_registry(tmp_path).names()
    assert "whatsapp_send" not in names


def test_reader_format_empty():
    assert "No messages" in WhatsAppReader.format([])
    text = WhatsAppReader.format(
        [{"direction": "in", "text": "namaste", "meta": ""}],
        title="Priya",
    )
    assert text.startswith("Chat: Priya")
    assert "Them: namaste" in text
    raw = WhatsAppReader.format(
        [{"direction": "in", "text": "hello from panel", "meta": "raw-panel"}],
        title="Guptaji",
    )
    assert "raw conversation panel" in raw
    assert "hello from panel" in raw


def test_parse_extract_payload():
    from ribhus.channels.whatsapp_web.reader import parse_extract

    msgs, debug = parse_extract(
        {"messages": [{"text": "hi", "outgoing": False, "meta": ""}], "debug": {"pre": 2}}
    )
    assert msgs[0]["text"] == "hi"
    assert msgs[0]["direction"] == "in"
    assert debug["pre"] == 2
    msgs, _ = parse_extract([{"text": "yo", "outgoing": True}])
    assert msgs[0]["direction"] == "out"


def test_whatsapp_approver_edit(monkeypatch):
    answers = iter(["e", "I'll be late"])
    monkeypatch.setattr(
        "ribhus.cli.main.console.input", lambda *a, **k: next(answers)
    )
    args = {"contact": "Rahul", "message": "original"}
    assert _whatsapp_send_approver(args) is True
    assert args["message"] == "I'll be late"


def test_whatsapp_approver_cancel(monkeypatch):
    monkeypatch.setattr("ribhus.cli.main.console.input", lambda *a, **k: "c")
    args = {"contact": "Rahul", "message": "hi"}
    assert _whatsapp_send_approver(args) is False
    assert args["message"] == "hi"


@pytest.mark.asyncio
async def test_open_chat_reports_not_found():
    nav = _FakeNavigator()
    nav.fail = "No chat matching Ghost"
    tool = WhatsAppOpenChatTool(nav, WhatsAppPolicy(cooldown_seconds=0))
    result = await tool.execute({"contact": "Ghost"})
    assert result.startswith("Error")
    assert "Ghost" in result or "matching" in result.lower()


class _FakeNavigator:
    def __init__(self) -> None:
        self.opened: str | None = None
        self.title: str | None = None
        self.force_title: str | None = None
        self.fail: str | None = None

    async def open_chat(self, name: str) -> str:
        if self.fail:
            raise ChatNotFound(self.fail)
        self.opened = name
        self.title = self.force_title or name
        return self.title

    async def current_title(self) -> str | None:
        return self.title

    async def main_open(self) -> bool:
        return self.opened is not None or self.title is not None


@pytest.mark.asyncio
async def test_read_after_profile_details_false_alarm():
    nav = _FakeNavigator()
    nav.fail = "Opened 'Profile details', which does not match 'Guptaji'."
    nav.title = "Guptaji"
    nav.opened = "Guptaji"
    tool = WhatsAppReadTool(nav, _FakeReader(), WhatsAppPolicy(cooldown_seconds=0))
    result = await tool.execute({"contact": "Guptaji"})
    assert "Are you coming?" in result
    assert result.startswith("Chat: Guptaji") or "Guptaji" in result


class _FakeSender:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.cleared = 0

    async def send(self, text: str) -> None:
        self.sent.append(text)

    async def clear_compose(self) -> None:
        self.cleared += 1


class _FakeReader:
    async def read_messages(self, limit: int = 15):
        return [
            {"direction": "in", "text": "Are you coming?", "meta": ""},
            {"direction": "out", "text": "On my way", "meta": ""},
        ]

    def format(self, messages, *, title=None, debug=None):
        return WhatsAppReader.format(messages, title=title, debug=debug)
