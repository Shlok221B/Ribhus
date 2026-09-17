"""Agent-facing WhatsApp Web tools.

Sends always set force_approval so the policy engine cannot auto-approve them,
including when RIBHUS_AUTO_APPROVE=true.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ribhus.channels.whatsapp_web.navigator import (
    ChatNotFound,
    WhatsAppNavigator,
    is_chrome_label,
    names_match,
)
from ribhus.channels.whatsapp_web.policy import (
    CHANNEL_LABEL,
    TOS_WARNING,
    WhatsAppKilled,
    WhatsAppPolicy,
    WhatsAppPolicyError,
)
from ribhus.channels.whatsapp_web.reader import WhatsAppReader
from ribhus.channels.whatsapp_web.sender import WhatsAppSender
from ribhus.channels.whatsapp_web.session import WhatsAppSession
from ribhus.policy.levels import RiskLevel
from ribhus.tools.base import Tool
from ribhus.tools.registry import ToolRegistry


class WhatsAppStatusTool(Tool):
    name = "whatsapp_status"
    description = (
        f"[{CHANNEL_LABEL}] Check whether the WhatsApp Web channel is enabled, "
        "killed, or already logged in. Does not send anything. "
        "Pass check_login=true to open the session and wait for a QR scan if needed."
    )
    risk_level = RiskLevel.LOW.value

    def __init__(self, session: WhatsAppSession, policy: WhatsAppPolicy) -> None:
        self.session = session
        self.policy = policy

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "check_login": {
                    "type": "boolean",
                    "description": "Launch WhatsApp Web and wait for login (default false)",
                    "default": False,
                }
            },
        }

    async def execute(self, arguments: dict[str, Any]) -> str:
        status = self.policy.status()
        lines = [
            CHANNEL_LABEL,
            TOS_WARNING,
            f"killed={status['killed']} enabled={status['enabled']}",
            f"rate: {status['sends_per_minute']}/min, {status['sends_per_hour']}/hour, "
            f"cooldown {status['cooldown_seconds']}s",
            f"sends last hour: {status['sends_last_hour']}",
            f"profile: {self.session.user_data_dir}",
        ]
        check = bool(arguments.get("check_login"))
        if self.policy.is_killed():
            lines.append("Channel is stopped. Resume with `ribhus whatsapp resume`.")
            return "\n".join(lines)
        if check:
            try:
                await self.session.ensure_logged_in()
                state = await self.session.login_state()
            except Exception as exc:  # noqa: BLE001
                return "\n".join(lines) + f"\nlogin error: {exc}"
            lines.append(f"logged_in={state.get('logged_in')} qr_visible={state.get('qr_visible')}")
        else:
            snap = self.session.snapshot()
            lines.append(
                f"browser_started={snap['started']} headed={snap['headed']}"
            )
        return "\n".join(lines)


class WhatsAppOpenChatTool(Tool):
    name = "whatsapp_open_chat"
    description = (
        f"[{CHANNEL_LABEL}] Find and open a single WhatsApp chat by contact or "
        "group name. Read-only besides focusing the chat. Never use for bulk."
    )
    risk_level = RiskLevel.MEDIUM.value

    def __init__(
        self,
        navigator: WhatsAppNavigator,
        policy: WhatsAppPolicy,
    ) -> None:
        self.navigator = navigator
        self.policy = policy

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "contact": {
                    "type": "string",
                    "description": "Exact or partial name of one contact or group",
                }
            },
            "required": ["contact"],
        }

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        if self.policy.is_killed():
            return (
                "Error: WhatsApp channel is stopped (kill switch or "
                "RIBHUS_WHATSAPP_ENABLED=false). "
                "Resume with `ribhus whatsapp resume` if you intend to continue."
            )
        return None

    async def execute(self, arguments: dict[str, Any]) -> str:
        try:
            self.policy.assert_alive()
        except WhatsAppKilled as exc:
            return f"Error: {exc}"
        contact = arguments.get("contact")
        if isinstance(contact, (list, tuple)):
            return "Error: open exactly one chat. Bulk is not allowed."
        name = str(contact or "").strip()
        if not name:
            return "Error: contact is required"
        try:
            title = await self.navigator.open_chat(name)
        except ChatNotFound as exc:
            return f"Error: {exc}"
        except Exception as exc:  # noqa: BLE001
            return f"Error opening WhatsApp chat: {exc}"
        return f"Opened WhatsApp chat: {title}"


class WhatsAppReadTool(Tool):
    name = "whatsapp_read"
    description = (
        f"[{CHANNEL_LABEL}] Read the latest messages in a WhatsApp chat. "
        "Optionally pass contact to open that chat first. Use this before drafting a reply."
    )
    risk_level = RiskLevel.MEDIUM.value

    def __init__(
        self,
        navigator: WhatsAppNavigator,
        reader: WhatsAppReader,
        policy: WhatsAppPolicy,
    ) -> None:
        self.navigator = navigator
        self.reader = reader
        self.policy = policy

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "contact": {
                    "type": "string",
                    "description": "Optional contact/group to open first",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max messages to return (default 15, max 40)",
                    "default": 15,
                },
            },
        }

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        if self.policy.is_killed():
            return (
                "Error: WhatsApp channel is stopped (kill switch or "
                "RIBHUS_WHATSAPP_ENABLED=false). "
                "Resume with `ribhus whatsapp resume` if you intend to continue."
            )
        return None

    async def execute(self, arguments: dict[str, Any]) -> str:
        try:
            self.policy.assert_alive()
        except WhatsAppKilled as exc:
            return f"Error: {exc}"
        contact = arguments.get("contact")
        title = None
        open_error: str | None = None
        if contact:
            if isinstance(contact, (list, tuple)):
                return "Error: read exactly one chat. Bulk is not allowed."
            name = str(contact).strip()
            try:
                title = await self.navigator.open_chat(name)
            except ChatNotFound as exc:
                open_error = str(exc)
                # Chat is often already open; "Profile details" used to abort here.
                if await self.navigator.main_open():
                    title = await self.navigator.current_title() or name
                else:
                    return f"Error: {exc}"
            except Exception as exc:  # noqa: BLE001
                return f"Error opening WhatsApp chat: {exc}"
            await asyncio.sleep(0.8)
        else:
            title = await self.navigator.current_title()
        try:
            messages = await self.reader.read_messages(int(arguments.get("limit") or 15))
        except Exception as exc:  # noqa: BLE001
            return f"Error reading WhatsApp messages: {exc}"
        debug = getattr(self.reader, "last_debug", None)
        body = self.reader.format(messages, title=title, debug=debug)
        if open_error and not messages:
            return f"Error: {open_error}\n{body}"
        return body


class WhatsAppSendTool(Tool):
    name = "whatsapp_send"
    description = (
        f"[{CHANNEL_LABEL}] Send one WhatsApp message to one named contact. "
        "ALWAYS pauses for explicit user approval (approve / edit / cancel) "
        "before typing anything into WhatsApp. Never bulk, never spam, never "
        "bypass approval. Draft the reply from whatsapp_read first."
    )
    risk_level = RiskLevel.MEDIUM.value
    force_approval = True

    def __init__(
        self,
        navigator: WhatsAppNavigator,
        sender: WhatsAppSender,
        policy: WhatsAppPolicy,
    ) -> None:
        self.navigator = navigator
        self.sender = sender
        self.policy = policy

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "contact": {
                    "type": "string",
                    "description": "One contact or group name (must match the open chat)",
                },
                "message": {
                    "type": "string",
                    "description": "The single message to send after approval",
                },
            },
            "required": ["contact", "message"],
        }

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        if self.policy.is_killed():
            return (
                "Error: WhatsApp channel is stopped (kill switch or "
                "RIBHUS_WHATSAPP_ENABLED=false). "
                "Resume with `ribhus whatsapp resume` if you intend to continue."
            )
        reason = self.policy.refuse_reason(
            arguments.get("contact"), arguments.get("message")
        )
        if reason:
            return f"Error: {reason}"
        return None

    async def execute(self, arguments: dict[str, Any]) -> str:
        contact = arguments.get("contact")
        message = arguments.get("message")
        try:
            self.policy.assert_can_send(contact, message)
        except (WhatsAppKilled, WhatsAppPolicyError) as exc:
            return f"Error: {exc}"

        name = str(contact).strip()
        text = str(message).strip()
        try:
            title = await self.navigator.open_chat(name)
        except ChatNotFound as exc:
            return f"Error: {exc}"
        except Exception as exc:  # noqa: BLE001
            return f"Error opening WhatsApp chat: {exc}"

        if title and not names_match(title, name) and not is_chrome_label(title):
            return (
                f"Error: open chat is '{title}', not '{name}'. Refusing to send."
            )

        # Re-check kill switch after chat navigation (user may have flipped it).
        try:
            self.policy.assert_can_send(name, text)
        except (WhatsAppKilled, WhatsAppPolicyError) as exc:
            return f"Error: {exc}"

        try:
            await self.sender.send(text)
        except Exception as exc:  # noqa: BLE001
            await self.sender.clear_compose()
            return f"Error sending WhatsApp message: {exc}"

        self.policy.record_send(name, text)
        return f"Sent WhatsApp message to {title or name} ({len(text)} chars)."


def register_whatsapp_tools(
    registry: ToolRegistry,
    session: WhatsAppSession,
    policy: WhatsAppPolicy,
) -> None:
    navigator = WhatsAppNavigator(session)
    reader = WhatsAppReader(session)
    sender = WhatsAppSender(session)
    registry.register(WhatsAppStatusTool(session, policy))
    registry.register(WhatsAppOpenChatTool(navigator, policy))
    registry.register(WhatsAppReadTool(navigator, reader, policy))
    registry.register(WhatsAppSendTool(navigator, sender, policy))
