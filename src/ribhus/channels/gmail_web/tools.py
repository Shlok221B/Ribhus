"""Agent-facing Gmail Web tools (browser automation, WhatsApp-style)."""

from __future__ import annotations

import json
from typing import Any

from ribhus.channels.gmail_web.navigator import GmailNavigator, ThreadNotFound
from ribhus.channels.gmail_web.policy import (
    CHANNEL_LABEL,
    TOS_WARNING,
    EmailKilled,
    EmailPolicy,
    EmailPolicyError,
)
from ribhus.channels.gmail_web.reader import GmailReader
from ribhus.channels.gmail_web.sender import GmailSender
from ribhus.channels.gmail_web.session import GmailSession
from ribhus.policy.levels import RiskLevel
from ribhus.tools.base import Tool
from ribhus.tools.registry import ToolRegistry


def resolve_email_send_mode(arguments: dict[str, Any]) -> str:
    """Pick reply vs new. Prefer new when a recipient is present."""
    raw = str(arguments.get("mode") or "").strip().lower()
    to = str(arguments.get("to") or "").strip()
    subject = str(arguments.get("subject") or "").strip()
    if raw in {"new", "reply"}:
        if raw == "reply" and to and "@" in to:
            # Model often leaves default mode=reply while supplying to/subject.
            return "new"
        return raw
    if to and "@" in to:
        return "new"
    if subject and to:
        return "new"
    return "reply"


class EmailStatusTool(Tool):
    name = "email_status"
    description = (
        f"[{CHANNEL_LABEL}] Check whether Gmail Web is enabled, killed, or "
        "logged in. Pass check_login=true to open Chromium and wait for Google sign-in."
    )
    risk_level = RiskLevel.LOW.value

    def __init__(self, session: GmailSession, policy: EmailPolicy) -> None:
        self.session = session
        self.policy = policy

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "check_login": {
                    "type": "boolean",
                    "description": "Open Gmail and wait for login if needed",
                    "default": False,
                }
            },
            "required": [],
        }

    async def execute(self, arguments: dict[str, Any]) -> str:
        payload = {
            "channel": CHANNEL_LABEL,
            **self.policy.status(),
            **self.session.snapshot(),
            "warning": TOS_WARNING,
        }
        if arguments.get("check_login"):
            try:
                self.policy.assert_alive()
                await self.session.ensure_logged_in()
                payload.update(await self.session.login_state())
            except Exception as exc:  # noqa: BLE001
                payload["login_error"] = str(exc)
        else:
            payload.update(await self.session.login_state())
        return json.dumps(payload, indent=2, default=str)


class EmailListTool(Tool):
    name = "email_list"
    description = (
        f"[{CHANNEL_LABEL}] List recent visible inbox threads (from, subject, snippet). "
        "Then email_open / email_reply with a subject query."
    )
    risk_level = RiskLevel.MEDIUM.value

    def __init__(self, navigator: GmailNavigator, policy: EmailPolicy) -> None:
        self.navigator = navigator
        self.policy = policy

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "How many threads (default 10)",
                    "default": 10,
                }
            },
            "required": [],
        }

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        try:
            self.policy.assert_alive()
        except EmailKilled as exc:
            return f"Error: {exc}"
        return None

    async def execute(self, arguments: dict[str, Any]) -> str:
        limit = int(arguments.get("limit") or 10)
        try:
            rows = await self.navigator.list_inbox(limit=limit)
        except Exception as exc:  # noqa: BLE001
            return f"Error listing Gmail inbox: {exc}"
        if not rows:
            return (
                "No inbox rows visible. Sign in via email_status check_login=true, "
                "or open Gmail in the headed window."
            )
        lines = [f"Gmail inbox ({len(rows)}):"]
        for i, row in enumerate(rows, 1):
            lines.append(
                f"{i}. from={row['from'] or '?'} | {row['subject']}"
                + (f" — {row['snippet'][:80]}" if row.get("snippet") else "")
            )
        lines.append(
            "Next: email_reply with query=<subject>, then email_send after approval."
        )
        return "\n".join(lines)


class EmailOpenTool(Tool):
    name = "email_open"
    description = (
        f"[{CHANNEL_LABEL}] Open one Gmail thread by subject/search query."
    )
    risk_level = RiskLevel.MEDIUM.value

    def __init__(self, navigator: GmailNavigator, policy: EmailPolicy) -> None:
        self.navigator = navigator
        self.policy = policy

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Subject fragment or search query",
                }
            },
            "required": ["query"],
        }

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        try:
            self.policy.assert_alive()
        except EmailKilled as exc:
            return f"Error: {exc}"
        if not str(arguments.get("query") or "").strip():
            return "Error: query is required"
        return None

    async def execute(self, arguments: dict[str, Any]) -> str:
        query = str(arguments.get("query") or "").strip()
        try:
            subject = await self.navigator.open_thread(query)
        except ThreadNotFound as exc:
            return f"Error: {exc}"
        except Exception as exc:  # noqa: BLE001
            return f"Error opening Gmail thread: {exc}"
        return f"Opened Gmail thread: {subject}"


class EmailReadTool(Tool):
    name = "email_read"
    description = (
        f"[{CHANNEL_LABEL}] Read the currently open Gmail thread. "
        "Call email_open or email_reply first."
    )
    risk_level = RiskLevel.MEDIUM.value

    def __init__(self, reader: GmailReader, policy: EmailPolicy) -> None:
        self.reader = reader
        self.policy = policy

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max messages in thread to return",
                    "default": 8,
                }
            },
            "required": [],
        }

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        try:
            self.policy.assert_alive()
        except EmailKilled as exc:
            return f"Error: {exc}"
        return None

    async def execute(self, arguments: dict[str, Any]) -> str:
        limit = int(arguments.get("limit") or 8)
        try:
            subject, messages = await self.reader.read(limit=limit)
        except Exception as exc:  # noqa: BLE001
            return f"Error reading Gmail thread: {exc}"
        body = self.reader.format(subject, messages)
        return (
            f"{body}\n\n"
            "Next: draft a reply, then email_send with mode=reply and body=..."
        )


class EmailReplyTool(Tool):
    name = "email_reply"
    description = (
        f"[{CHANNEL_LABEL}] Open a thread by query and read it in one step "
        "(like whatsapp_reply). Then draft and call email_send mode=reply."
    )
    risk_level = RiskLevel.MEDIUM.value

    def __init__(
        self,
        navigator: GmailNavigator,
        reader: GmailReader,
        policy: EmailPolicy,
    ) -> None:
        self.navigator = navigator
        self.reader = reader
        self.policy = policy

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Subject fragment or search query",
                },
                "limit": {
                    "type": "integer",
                    "default": 8,
                },
            },
            "required": ["query"],
        }

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        try:
            self.policy.assert_alive()
        except EmailKilled as exc:
            return f"Error: {exc}"
        if not str(arguments.get("query") or "").strip():
            return "Error: query is required"
        return None

    async def execute(self, arguments: dict[str, Any]) -> str:
        query = str(arguments.get("query") or "").strip()
        limit = int(arguments.get("limit") or 8)
        try:
            subject = await self.navigator.open_thread(query)
            opened, messages = await self.reader.read(limit=limit)
        except ThreadNotFound as exc:
            return f"Error: {exc}"
        except Exception as exc:  # noqa: BLE001
            return f"Error in email_reply: {exc}"
        title = opened or subject
        body = self.reader.format(title, messages)
        return (
            f"{body}\n\n"
            "Next: draft one reply, then call email_send with "
            "mode=reply and body=<your draft> (approval required)."
        )


class EmailSendTool(Tool):
    name = "email_send"
    description = (
        f"[{CHANNEL_LABEL}] Send via Gmail Web. ALWAYS pauses for explicit approval. "
        "For a NEW email to an address: mode=new with to, subject, and body. "
        "For a reply in an already-open thread: mode=reply with body only. "
        "If the user gives an email address, ALWAYS use mode=new. "
        "One recipient only. Never bulk."
    )
    risk_level = RiskLevel.HIGH.value
    force_approval = True

    def __init__(
        self,
        sender: GmailSender,
        policy: EmailPolicy,
    ) -> None:
        self.sender = sender
        self.policy = policy

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["reply", "new"],
                    "description": (
                        "new = compose to/subject/body; reply = send in open thread. "
                        "Use new whenever 'to' is an email address."
                    ),
                    "default": "new",
                },
                "body": {"type": "string", "description": "Message body"},
                "to": {
                    "type": "string",
                    "description": "Recipient (required for mode=new)",
                },
                "subject": {
                    "type": "string",
                    "description": "Subject (required for mode=new)",
                },
            },
            "required": ["body"],
        }

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        mode = resolve_email_send_mode(arguments)
        body = str(arguments.get("body") or "")
        to = str(arguments.get("to") or "")
        subject = str(arguments.get("subject") or "")
        if mode == "new":
            if not to.strip() or "@" not in to:
                return "Error: mode=new requires a valid to email address"
            if not subject.strip():
                return "Error: mode=new requires subject"
        try:
            self.policy.assert_can_send(to, subject or "(reply)", body)
        except (EmailKilled, EmailPolicyError) as exc:
            return f"Error: {exc}"
        arguments["mode"] = mode
        return None

    async def execute(self, arguments: dict[str, Any]) -> str:
        mode = resolve_email_send_mode(arguments)
        body = str(arguments.get("body") or "").strip()
        to = str(arguments.get("to") or "").strip()
        subject = str(arguments.get("subject") or "").strip()
        try:
            self.policy.assert_can_send(to, subject or "(reply)", body)
        except (EmailKilled, EmailPolicyError) as exc:
            return f"Error: {exc}"

        try:
            if mode == "new":
                await self.sender.send_new(to=to, subject=subject, body=body)
                self.policy.record_send(to, subject)
                return f"Sent new Gmail message to {to} — subject={subject!r}."
            await self.sender.send_reply(body)
            self.policy.record_send(to or "(thread)", subject or "(reply)")
            return f"Sent Gmail reply ({len(body)} chars)."
        except Exception as exc:  # noqa: BLE001
            return (
                f"Error sending Gmail message: {exc}. "
                "Call email_send again with the same arguments if the user still wants to send."
            )


def register_email_tools(
    registry: ToolRegistry,
    session: GmailSession,
    policy: EmailPolicy,
) -> None:
    navigator = GmailNavigator(session)
    reader = GmailReader(session)
    sender = GmailSender(session)
    registry.register(EmailStatusTool(session, policy))
    registry.register(EmailListTool(navigator, policy))
    registry.register(EmailOpenTool(navigator, policy))
    registry.register(EmailReadTool(reader, policy))
    registry.register(EmailReplyTool(navigator, reader, policy))
    registry.register(EmailSendTool(sender, policy))
