"""Unit tests for WhatsApp Note to Self inbox (no Chromium required)."""

from __future__ import annotations

from pathlib import Path

from ribhus.channels.whatsapp_web.inbox import (
    RIBHUS_PREFIX,
    InboxCursorStore,
    format_wa_reply,
    is_query_candidate,
    is_ribhus_reply,
    message_fingerprint,
    pick_new_queries,
    resolve_inbox_aliases,
)


def test_resolve_inbox_aliases_default():
    aliases = resolve_inbox_aliases(None)
    assert "Message yourself" in aliases
    assert "You" in aliases
    assert "Note to Self" in aliases


def test_resolve_inbox_aliases_custom_first():
    aliases = resolve_inbox_aliases("My Notes")
    assert aliases[0] == "My Notes"
    assert "Message yourself" in aliases


def test_is_ribhus_reply_and_query_filter():
    assert is_ribhus_reply(f"{RIBHUS_PREFIX} hello")
    assert is_ribhus_reply(f"  {RIBHUS_PREFIX} x")
    assert not is_ribhus_reply("research Flipkart")
    assert is_query_candidate({"text": "book Goa hotels", "direction": "out"})
    assert not is_query_candidate(
        {"text": f"{RIBHUS_PREFIX} done", "direction": "out"}
    )
    assert not is_query_candidate({"text": "  ", "direction": "out"})
    assert not is_query_candidate(
        {"text": "blob", "meta": "raw-panel", "direction": "in"}
    )


def test_message_fingerprint_prefers_id():
    a = message_fingerprint({"id": "true_123", "text": "hi", "direction": "out"})
    b = message_fingerprint({"id": "true_123", "text": "other", "direction": "in"})
    assert a == b == "id:true_123"
    c = message_fingerprint({"text": "hi", "direction": "out"})
    d = message_fingerprint({"text": "hi", "direction": "out"})
    assert c == d
    assert c.startswith("h:")


def test_pick_new_queries_skips_seen_and_ribhus():
    msgs = [
        {"id": "1", "text": "old query", "direction": "out"},
        {"id": "2", "text": f"{RIBHUS_PREFIX} answer", "direction": "out"},
        {"id": "3", "text": "new query", "direction": "out"},
    ]
    seen = {message_fingerprint(msgs[0])}
    fresh = pick_new_queries(msgs, seen=seen)
    assert len(fresh) == 1
    assert fresh[0]["text"] == "new query"


def test_format_wa_reply_prefix_and_truncate():
    short = format_wa_reply("**hello** world", max_chars=1500)
    assert short.startswith(RIBHUS_PREFIX)
    assert "**" not in short
    assert "hello world" in short

    long = format_wa_reply("x" * 5000, max_chars=200)
    assert long.startswith(RIBHUS_PREFIX)
    assert "full answer on Mac" in long
    assert len(long) <= 200


def test_inbox_cursor_seed_and_persist(tmp_path: Path):
    path = tmp_path / "cursor.json"
    store = InboxCursorStore(path)
    store.load()
    assert store.seen == set()

    msgs = [
        {"id": "a", "text": "one", "direction": "out"},
        {"id": "b", "text": "two", "direction": "out"},
    ]
    store.seed_from_messages(msgs)
    assert message_fingerprint(msgs[0]) in store.seen
    assert path.exists()

    again = InboxCursorStore(path)
    again.load()
    assert again.seen == store.seen

    fresh = pick_new_queries(msgs, seen=again.seen)
    assert fresh == []


def test_parse_approval_reply():
    from ribhus.channels.whatsapp_web.inbox import parse_approval_reply

    assert parse_approval_reply("approve") == ("approve", None)
    assert parse_approval_reply("YES") == ("approve", None)
    assert parse_approval_reply("cancel") == ("cancel", None)
    assert parse_approval_reply("edit: hi Guptaji") == ("edit", "hi Guptaji")
    assert parse_approval_reply("e: shorter") == ("edit", "shorter")
    assert parse_approval_reply(f"{RIBHUS_PREFIX} noise") is None
    assert parse_approval_reply("random hotel question") is None


def test_format_approval_request_whatsapp():
    from ribhus.channels.whatsapp_web.inbox import format_approval_request

    text = format_approval_request(
        "whatsapp_send",
        {"contact": "Guptaji", "message": "Goa hotels…"},
    )
    assert text.startswith(RIBHUS_PREFIX)
    assert "Guptaji" in text
    assert "approve" in text.lower()


def test_prefers_whatsapp_channel():
    from ribhus.agent.loop import (
        looks_whatsapp_read_only,
        prefers_email_channel,
        prefers_whatsapp_channel,
        send_tool_nudge_for_prompt,
    )

    q = "Do research on hotels in goa for 22 oct and send details to guptaji on WhatsApp"
    assert prefers_whatsapp_channel(q)
    assert not prefers_email_channel(q)
    assert prefers_whatsapp_channel("send this to Rahul")
    assert prefers_email_channel("email the report to a@b.com")
    assert not prefers_whatsapp_channel("email the report to a@b.com")

    nudge = send_tool_nudge_for_prompt(q, has_whatsapp=True, has_email=True)
    assert "whatsapp_send" in nudge
    assert "email_send now" not in nudge

    email_nudge = send_tool_nudge_for_prompt(
        "send email about pending tasks", has_whatsapp=True, has_email=True
    )
    assert "email_send" in email_nudge

    summary = "summarize my chat with guptaji"
    assert looks_whatsapp_read_only(summary)
    summary_nudge = send_tool_nudge_for_prompt(
        summary, has_whatsapp=True, has_email=True
    )
    assert "SUMMARIZE" in summary_nudge or "summary" in summary_nudge.lower()
    assert "Do NOT call whatsapp_send" in summary_nudge
    assert not looks_whatsapp_read_only(
        "summarize my chat with guptaji then send it to Rahul"
    )
