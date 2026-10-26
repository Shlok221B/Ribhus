from __future__ import annotations

from bs4 import BeautifulSoup

from ribhus.channels.whatsapp_web.inbox import parse_approval_reply
from ribhus.channels.whatsapp_web.navigator import names_match
from ribhus.channels.whatsapp_web.policy import WhatsAppKilled, WhatsAppPolicy
from ribhus.channels.whatsapp_web.reader import parse_extract
from ribhus.channels.whatsapp_web.tools import WhatsAppSendTool
from ribhus.eval.harness import repo_root, temp_workspace
from ribhus.eval.models import EvalCase, EvalSkip


def kill_switch_persists() -> None:
    with temp_workspace() as workspace:
        path = workspace / ".ribhus" / "whatsapp.killed"
        policy = WhatsAppPolicy(kill_path=path, cooldown_seconds=0)
        assert not policy.is_killed()
        policy.kill()
        assert path.exists()
        other = WhatsAppPolicy(kill_path=path, cooldown_seconds=0)
        assert other.is_killed()
        try:
            other.assert_can_send("Rahul", "hi")
        except WhatsAppKilled:
            pass
        else:
            raise AssertionError("expected WhatsAppKilled")
        other.resume()
        assert not path.exists()
        assert not other.is_killed()


def send_force_approval_flag() -> None:
    assert WhatsAppSendTool.force_approval is True


def fixture_reader_texts() -> None:
    root = repo_root()
    if root is None:
        raise EvalSkip("whatsapp fixture lives in the git checkout")
    html_path = root / "tests" / "fixtures" / "whatsapp_chat.html"
    if not html_path.is_file():
        raise EvalSkip(f"missing {html_path}")
    html = html_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    texts = [el.get_text() for el in soup.select("span.selectable-text")]
    assert "Arre theeke" in texts
    assert "Haan bhai" in texts
    messages, _debug = parse_extract(
        {
            "messages": [
                {"text": "Arre theeke", "outgoing": False, "meta": "Guptaji"},
                {"text": "Haan bhai", "outgoing": False},
            ],
            "debug": {"main": True},
        }
    )
    assert [m["text"] for m in messages] == ["Arre theeke", "Haan bhai"]
    assert messages[0]["direction"] == "in"


def chat_name_matching() -> None:
    assert names_match("Rahul", "rahul")
    assert names_match("Gupta ji", "Guptaji")
    assert not names_match("Rahul", "Ananya")


def inbox_approval_replies() -> None:
    assert parse_approval_reply("approve") == ("approve", None)
    assert parse_approval_reply("cancel") == ("cancel", None)
    action, edited = parse_approval_reply("edit: Kal milte hain")
    assert action == "edit"
    assert edited == "Kal milte hain"


def rate_limit_cooldown() -> None:
    policy = WhatsAppPolicy(cooldown_seconds=8, sends_per_minute=3, sends_per_hour=10)
    policy.record_send("Rahul", "hi")
    reason = policy.refuse_reason("Priya", "hello")
    assert reason and "Cooldown" in reason

    burst = WhatsAppPolicy(cooldown_seconds=0, sends_per_minute=1, sends_per_hour=10)
    burst.record_send("A", "one")
    reason = burst.refuse_reason("B", "two")
    assert reason and "per minute" in reason


CASES = [
    EvalCase("whatsapp-kill", "whatsapp", "policy.kill", "Kill switch persists on disk", kill_switch_persists),
    EvalCase("whatsapp-force-approval", "whatsapp", "whatsapp_send", "Send tool requires approval", send_force_approval_flag),
    EvalCase("whatsapp-fixture", "whatsapp", "reader", "Chat fixture extracts messages", fixture_reader_texts),
    EvalCase("whatsapp-names", "whatsapp", "navigator", "Chat name matching", chat_name_matching),
    EvalCase("whatsapp-inbox", "whatsapp", "inbox", "Note-to-self approve/cancel/edit", inbox_approval_replies),
    EvalCase("whatsapp-rate-limit", "whatsapp", "policy", "Cooldown and per-minute cap", rate_limit_cooldown),
]
