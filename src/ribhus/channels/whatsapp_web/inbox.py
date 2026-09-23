"""WhatsApp Note to Self → Ribhus inbox (poll, dedupe, short reply)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ribhus.channels.whatsapp_web.navigator import (
    ChatNotFound,
    WhatsAppNavigator,
    names_match,
)
from ribhus.channels.whatsapp_web.policy import (
    WhatsAppKilled,
    WhatsAppPolicy,
    WhatsAppPolicyError,
)
from ribhus.channels.whatsapp_web.reader import WhatsAppReader
from ribhus.channels.whatsapp_web.sender import WhatsAppSender

RIBHUS_PREFIX = "[Ribhus]"
APPROVAL_NOTICE = (
    f"{RIBHUS_PREFIX} Need approval — reply here with approve / cancel / "
    "edit: <new text> (also shown in the Ribhus terminal)."
)
INBOX_QUERY_PREFIX = (
    "[Via WhatsApp Note to Self] If this task says to message/send to a person "
    "or 'on WhatsApp', use whatsapp_send — never email_send/Gmail unless they "
    "explicitly ask for email or give an @ address.\n\n"
)

NOTE_TO_SELF_ALIASES: tuple[str, ...] = (
    "Message yourself",
    "You",
    "Note to Self",
    "Notes to self",
    "Mensaje para ti",
    "Mensagens para mim",
)

OnQuery = Callable[[str], Awaitable[str]]
OnStatus = Callable[[str], None]


def is_ribhus_reply(text: object) -> bool:
    return str(text or "").strip().startswith(RIBHUS_PREFIX)


def message_fingerprint(msg: dict[str, Any]) -> str:
    mid = str(msg.get("id") or "").strip()
    if mid:
        return f"id:{mid}"
    text = str(msg.get("text") or "").strip()
    direction = str(msg.get("direction") or "")
    meta = str(msg.get("meta") or "").strip()[:120]
    digest = hashlib.sha1(
        f"{direction}|{meta}|{text}".encode("utf-8", errors="replace")
    ).hexdigest()[:16]
    return f"h:{digest}"


def format_wa_reply(text: str, *, max_chars: int = 1500) -> str:
    """Prefix + truncate for WhatsApp; plain-ish text."""
    body = str(text or "").strip()
    if not body:
        body = "(no answer)"
    # Strip common markdown noise for mobile readability.
    body = body.replace("**", "").replace("__", "").replace("`", "")
    limit = max(80, int(max_chars))
    prefix = f"{RIBHUS_PREFIX} "
    budget = limit - len(prefix)
    if len(body) <= budget:
        return prefix + body
    suffix = "… (full answer on Mac)"
    keep = max(40, budget - len(suffix))
    return prefix + body[:keep].rstrip() + suffix


def is_query_candidate(msg: dict[str, Any]) -> bool:
    text = str(msg.get("text") or "").strip()
    if not text or is_ribhus_reply(text):
        return False
    if msg.get("meta") == "raw-panel":
        return False
    return True


def resolve_inbox_aliases(configured: str | None = None) -> list[str]:
    custom = str(configured or "").strip()
    if custom:
        return [custom, *NOTE_TO_SELF_ALIASES]
    return list(NOTE_TO_SELF_ALIASES)


def pick_new_queries(
    messages: list[dict[str, Any]],
    *,
    seen: set[str],
) -> list[dict[str, Any]]:
    """Return unseen non-Ribhus messages in chronological order."""
    out: list[dict[str, Any]] = []
    for msg in messages:
        fp = message_fingerprint(msg)
        if fp in seen:
            continue
        if not is_query_candidate(msg):
            continue
        out.append(msg)
    return out


@dataclass
class InboxCursorStore:
    """Persisted fingerprints so restarts skip already-handled messages."""

    path: Path
    max_seen: int = 200
    seen: set[str] = field(default_factory=set)

    def load(self) -> None:
        if not self.path.exists():
            self.seen = set()
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.seen = set()
            return
        items = raw.get("seen") if isinstance(raw, dict) else None
        if not isinstance(items, list):
            self.seen = set()
            return
        self.seen = {str(x) for x in items if str(x).strip()}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ordered = list(self.seen)[-self.max_seen :]
        self.path.write_text(
            json.dumps({"seen": ordered, "updated_at": time.time()}, indent=2)
            + "\n",
            encoding="utf-8",
        )

    def mark(self, fingerprints: list[str] | set[str]) -> None:
        self.seen.update(fingerprints)
        if len(self.seen) > self.max_seen:
            # Drop arbitrary extras; fingerprints are unordered in a set.
            self.seen = set(list(self.seen)[-self.max_seen :])
        self.save()

    def seed_from_messages(self, messages: list[dict[str, Any]]) -> None:
        """Mark current transcript as seen without running queries."""
        fps = [message_fingerprint(m) for m in messages]
        # Also mark Ribhus replies so they never become queries later.
        self.mark(fps)


async def open_note_to_self(
    navigator: WhatsAppNavigator,
    *,
    configured: str | None = None,
) -> str:
    """Open Message yourself / Note to Self, trying aliases in order."""
    aliases = resolve_inbox_aliases(configured)
    errors: list[str] = []
    for alias in aliases:
        try:
            title = await navigator.open_chat(alias)
            if title and (
                names_match(title, alias)
                or any(names_match(title, a) for a in aliases)
            ):
                return title
            # open_chat may return query on chrome-label path
            if title:
                return title
        except ChatNotFound as exc:
            errors.append(str(exc))
            continue
    hint = errors[-1] if errors else "No matching chat."
    raise ChatNotFound(
        "Could not open Note to Self / Message yourself. "
        f"Tried: {', '.join(aliases)}. {hint}"
    )


async def send_inbox_reply(
    *,
    sender: WhatsAppSender,
    policy: WhatsAppPolicy,
    contact: str,
    text: str,
) -> str:
    """Send a self-chat reply without Approve/Edit/Cancel (still rate-limited)."""
    policy.assert_can_send(contact, text)
    confirm = await sender.send(text)
    policy.record_send(contact, text)
    return confirm


def format_approval_request(tool_name: str, arguments: dict[str, Any]) -> str:
    """Draft shown on Note to Self for approve / edit / cancel."""
    name = str(tool_name or "tool")
    if name == "whatsapp_send":
        contact = str(arguments.get("contact") or "(unknown)").strip()
        draft = str(arguments.get("message") or "").strip()
        body = (
            f"{RIBHUS_PREFIX} APPROVAL NEEDED\n"
            f"Tool: whatsapp_send\n"
            f"To: {contact}\n\n"
            f"Draft:\n{draft}\n\n"
            "Reply with one of:\n"
            "approve\n"
            "cancel\n"
            "edit: your new message"
        )
    elif name == "email_send":
        to = str(arguments.get("to") or "(unknown)").strip()
        subject = str(arguments.get("subject") or "").strip()
        draft = str(arguments.get("body") or "").strip()
        body = (
            f"{RIBHUS_PREFIX} APPROVAL NEEDED\n"
            f"Tool: email_send\n"
            f"To: {to}\n"
            f"Subject: {subject}\n\n"
            f"Body:\n{draft}\n\n"
            "Reply with one of:\n"
            "approve\n"
            "cancel\n"
            "edit: your new body"
        )
    else:
        preview = json.dumps(arguments, indent=2, default=str)
        if len(preview) > 900:
            preview = preview[:900] + "…"
        body = (
            f"{RIBHUS_PREFIX} APPROVAL NEEDED\n"
            f"Tool: {name}\n\n"
            f"{preview}\n\n"
            "Reply with: approve | cancel"
        )
    if len(body) > 3500:
        return body[:3490].rstrip() + "…"
    return body


def parse_approval_reply(text: object) -> tuple[str, str | None] | None:
    """Parse Note to Self reply → ('approve'|'cancel'|'edit', edited?) or None."""
    raw = str(text or "").strip()
    if not raw or is_ribhus_reply(raw):
        return None
    # Strip accidental Ribhus prefix if user quoted it
    if raw.startswith(RIBHUS_PREFIX):
        return None
    lower = raw.lower().strip()
    if lower in {"a", "approve", "yes", "y", "ok", "okay", "send"}:
        return "approve", None
    if lower in {"c", "cancel", "no", "n", "deny", "denied"}:
        return "cancel", None
    for prefix in ("edit:", "e:", "edit "):
        if lower.startswith(prefix):
            # Preserve original casing for the edited payload
            idx = raw.lower().find(prefix)
            edited = raw[idx + len(prefix) :].strip()
            if not edited:
                return None
            return "edit", edited
    if "\n" in raw and lower.startswith("edit"):
        parts = raw.split("\n", 1)
        edited = parts[1].strip() if len(parts) > 1 else ""
        if edited:
            return "edit", edited
    return None


async def wait_for_inbox_approval(
    *,
    navigator: WhatsAppNavigator,
    reader: WhatsAppReader,
    sender: WhatsAppSender,
    policy: WhatsAppPolicy,
    cursor: InboxCursorStore,
    tool_name: str,
    arguments: dict[str, Any],
    inbox_chat: str | None = None,
    timeout: float = 300.0,
    poll_interval: float = 2.0,
    on_status: OnStatus | None = None,
) -> bool:
    """Post draft to Note to Self; wait for approve / cancel / edit reply."""

    def status(msg: str) -> None:
        if on_status:
            on_status(msg)

    title = await open_note_to_self(navigator, configured=inbox_chat)
    # Ignore current transcript for the wait window.
    existing = await reader.read_messages(limit=40)
    cursor.mark({message_fingerprint(m) for m in existing})

    card = format_approval_request(tool_name, arguments)
    try:
        await send_inbox_reply(
            sender=sender, policy=policy, contact=title, text=card
        )
    except (WhatsAppKilled, WhatsAppPolicyError) as exc:
        status(f"Could not post approval card: {exc}")
        return False
    cursor.mark({message_fingerprint({"text": card, "direction": "out"})})
    status(
        "Approval posted to WhatsApp Note to Self — "
        "reply approve / cancel / edit: …"
    )

    deadline = time.time() + max(30.0, float(timeout))
    poll = max(1.0, float(poll_interval))
    while time.time() < deadline:
        if policy.is_killed():
            status("Kill switch — approval cancelled.")
            return False
        await asyncio.sleep(poll)
        try:
            title = await open_note_to_self(navigator, configured=inbox_chat)
            messages = await reader.read_messages(limit=40)
        except Exception as exc:  # noqa: BLE001
            status(f"Approval poll error: {exc}")
            continue

        for m in messages:
            if is_ribhus_reply(m.get("text")):
                cursor.mark({message_fingerprint(m)})
                continue
            fp = message_fingerprint(m)
            if fp in cursor.seen:
                continue
            parsed = parse_approval_reply(m.get("text"))
            if parsed is None:
                # Not an approval reply — leave unmarked so listen can pick it up later
                continue
            cursor.mark({fp})
            action, edited = parsed
            if action == "approve":
                status("Approved on WhatsApp.")
                return True
            if action == "cancel":
                status("Cancelled on WhatsApp.")
                return False
            if action == "edit" and edited:
                if tool_name == "whatsapp_send":
                    arguments["message"] = edited
                elif tool_name == "email_send":
                    arguments["body"] = edited
                status("Edited + approved on WhatsApp.")
                return True
    status("Approval timed out — cancelled.")
    try:
        await send_inbox_reply(
            sender=sender,
            policy=policy,
            contact=title,
            text=f"{RIBHUS_PREFIX} Approval timed out — cancelled.",
        )
    except Exception:  # noqa: BLE001
        pass
    return False


async def run_listen_loop(
    *,
    navigator: WhatsAppNavigator,
    reader: WhatsAppReader,
    sender: WhatsAppSender,
    policy: WhatsAppPolicy,
    cursor: InboxCursorStore,
    on_query: OnQuery,
    inbox_chat: str | None = None,
    interval: float = 3.0,
    reply_max: int = 1500,
    on_status: OnStatus | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """Poll Note to Self; run each new message through on_query; dual-reply."""

    def status(msg: str) -> None:
        if on_status:
            on_status(msg)

    cursor.load()
    policy.assert_alive()

    title = await open_note_to_self(navigator, configured=inbox_chat)
    status(f"Inbox open: {title}")

    # First poll: seed cursor so we don't replay history.
    messages = await reader.read_messages(limit=40)
    if not cursor.seen:
        cursor.seed_from_messages(messages)
        status(f"Seeded cursor with {len(messages)} existing message(s).")
    else:
        # Mark any Ribhus replies already on screen so they stay filtered.
        ribhus_fps = [
            message_fingerprint(m)
            for m in messages
            if is_ribhus_reply(m.get("text"))
        ]
        if ribhus_fps:
            cursor.mark(ribhus_fps)

    poll = max(1.0, float(interval))

    while True:
        if should_stop and should_stop():
            status("Stop requested.")
            return
        if policy.is_killed():
            status("WhatsApp kill switch engaged — listen stopped.")
            return

        try:
            # Stay on Note to Self if the user switched chats.
            current = await navigator.current_title()
            aliases = resolve_inbox_aliases(inbox_chat)
            if current and not any(names_match(current, a) for a in aliases):
                title = await open_note_to_self(navigator, configured=inbox_chat)

            messages = await reader.read_messages(limit=40)
            # Always mark Ribhus-prefixed as seen (our replies).
            for m in messages:
                if is_ribhus_reply(m.get("text")):
                    cursor.mark({message_fingerprint(m)})

            fresh = pick_new_queries(messages, seen=cursor.seen)
            for msg in fresh:
                if policy.is_killed():
                    status("WhatsApp kill switch engaged — listen stopped.")
                    return
                text = str(msg.get("text") or "").strip()
                fp = message_fingerprint(msg)
                status(f"Query: {text[:80]}{'…' if len(text) > 80 else ''}")
                try:
                    answer = await on_query(text)
                except Exception as exc:  # noqa: BLE001
                    answer = f"Error running Ribhus: {exc}"
                    status(str(answer))

                reply = format_wa_reply(answer, max_chars=reply_max)
                try:
                    # Re-focus inbox before sending.
                    title = await open_note_to_self(
                        navigator, configured=inbox_chat
                    )
                    await send_inbox_reply(
                        sender=sender,
                        policy=policy,
                        contact=title,
                        text=reply,
                    )
                    status("Replied on WhatsApp.")
                except (WhatsAppKilled, WhatsAppPolicyError) as exc:
                    status(f"Could not reply on WhatsApp: {exc}")
                except Exception as exc:  # noqa: BLE001
                    status(f"Could not reply on WhatsApp: {exc}")

                cursor.mark({fp, message_fingerprint({"text": reply, "direction": "out"})})

        except ChatNotFound as exc:
            status(f"Inbox chat missing: {exc}")
        except WhatsAppKilled:
            status("WhatsApp kill switch engaged — listen stopped.")
            return
        except Exception as exc:  # noqa: BLE001
            status(f"Listen poll error: {exc}")

        await asyncio.sleep(poll)
