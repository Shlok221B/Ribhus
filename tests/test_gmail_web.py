from __future__ import annotations

from pathlib import Path

import pytest

from ribhus.channels.gmail_web.policy import EmailKilled, EmailPolicy, EmailPolicyError
from ribhus.channels.gmail_web.session import gmail_url_is_inbox
from ribhus.channels.gmail_web.sender import _norm_email
from ribhus.channels.gmail_web.tools import EmailSendTool, resolve_email_send_mode
from ribhus.cli.main import _email_send_approver
from ribhus.policy.engine import PolicyEngine
from ribhus.tools.browser import BrowserSession, DomainNotAllowed
from ribhus.tools.registry import default_registry


def test_gmail_inbox_url_ignores_signin_and_recovery():
    assert gmail_url_is_inbox("https://mail.google.com/mail/u/0/#inbox")
    assert gmail_url_is_inbox("https://mail.google.com/mail/u/0/?pli=1")
    assert not gmail_url_is_inbox(
        "https://accounts.google.com/ServiceLogin?continue=https://mail.google.com/mail/u/0/"
    )
    assert not gmail_url_is_inbox(
        "https://accounts.google.com/v3/signin/challenge/ipp/verify"
    )
    assert not gmail_url_is_inbox("https://gds.google.com/web/recoveryoptions")


def test_norm_email():
    assert _norm_email("  Foo@Bar.COM ") == "foo@bar.com"


def test_resolve_email_send_mode():
    assert resolve_email_send_mode({"to": "a@b.com", "subject": "Hi", "body": "x"}) == "new"
    assert resolve_email_send_mode({"mode": "reply", "to": "a@b.com", "body": "x"}) == "new"
    assert resolve_email_send_mode({"mode": "new", "to": "a@b.com", "subject": "s", "body": "x"}) == "new"
    assert resolve_email_send_mode({"mode": "reply", "body": "thanks"}) == "reply"
    assert resolve_email_send_mode({"body": "thanks"}) == "reply"


def test_refuse_bad_email_shape():
    policy = EmailPolicy(cooldown_seconds=0)
    assert policy.refuse_reason("not-an-email", "s", "hello") is not None
    assert policy.refuse_reason("a@", "s", "hello") is not None
    assert policy.refuse_reason("a@b", "s", "hello") is not None
    assert policy.refuse_reason("a@b.com", "s", "hello") is None


def test_kill_switch_persists(tmp_path: Path):
    path = tmp_path / "email.killed"
    policy = EmailPolicy(kill_path=path, cooldown_seconds=0)
    assert not policy.is_killed()
    policy.kill()
    assert path.exists()
    other = EmailPolicy(kill_path=path, cooldown_seconds=0)
    assert other.is_killed()
    with pytest.raises(EmailKilled):
        other.assert_can_send("a@b.com", "hi", "body")
    other.resume()
    assert not path.exists()
    assert not other.is_killed()


def test_disabled_env_blocks_send():
    policy = EmailPolicy(enabled=False, cooldown_seconds=0)
    assert policy.is_killed()
    assert not policy.is_active()
    with pytest.raises(EmailKilled):
        policy.assert_alive()


def test_refuse_bulk_and_empty():
    policy = EmailPolicy(cooldown_seconds=0)
    assert policy.refuse_reason("a@b.com,c@d.com", "s", "hello") is not None
    assert policy.refuse_reason("a@b.com", "s", "") is not None
    assert policy.refuse_reason("not-an-email", "s", "hello") is not None
    assert policy.refuse_reason("a@b.com", "s", "hello") is None
    # Reply-in-thread may omit recipient
    assert policy.refuse_reason("", "(reply)", "hello") is None


def test_rate_limit(tmp_path: Path):
    policy = EmailPolicy(
        kill_path=tmp_path / "email.killed",
        sends_per_minute=1,
        sends_per_hour=2,
        cooldown_seconds=0,
    )
    policy.assert_can_send("a@b.com", "s", "one")
    policy.record_send("a@b.com", "s")
    with pytest.raises(EmailPolicyError, match="rate limit"):
        policy.assert_can_send("a@b.com", "s", "two")


def test_browser_blocks_gmail(tmp_path: Path):
    session = BrowserSession(user_data_dir=tmp_path / "browser")
    with pytest.raises(DomainNotAllowed, match="Gmail"):
        session.check_url("https://mail.google.com/mail/u/0/")
    with pytest.raises(DomainNotAllowed, match="Gmail"):
        session.check_url("https://gmail.com")


def test_email_tools_registered(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from ribhus.channels.gmail_web.session import GmailSession
    from ribhus.config import Settings

    settings = Settings(workspace=tmp_path)
    gmail = GmailSession(user_data_dir=tmp_path / "gmail_profile")
    policy = EmailPolicy(
        enabled=True,
        kill_path=tmp_path / "email.killed",
        cooldown_seconds=0,
    )
    registry = default_registry(
        settings.workspace,
        policy=PolicyEngine(auto_approve=True),
        gmail_session=gmail,
        email_policy=policy,
    )
    for name in (
        "email_status",
        "email_list",
        "email_open",
        "email_read",
        "email_reply",
        "email_send",
    ):
        assert registry.get(name) is not None
    send = registry.get("email_send")
    assert isinstance(send, EmailSendTool)
    assert send.force_approval is True


def test_email_send_approver_edit(monkeypatch):
    answers = iter(["e", "Edited body text"])
    monkeypatch.setattr(
        "ribhus.cli.main.console.input",
        lambda *_a, **_k: next(answers),
    )
    args = {"mode": "reply", "body": "original", "to": "", "subject": ""}
    assert _email_send_approver(args) is True
    assert args["body"] == "Edited body text"
