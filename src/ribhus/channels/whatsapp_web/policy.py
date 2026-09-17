"""Safety rails for the WhatsApp Web channel.

Non-negotiable: no bulk/spam, rate limits, kill switch, send never bypasses
approval (that last part is enforced with Tool.force_approval + this policy).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

CHANNEL_LABEL = "WhatsApp Web (browser automation — not the official WhatsApp Business API)"

TOS_WARNING = (
    "This channel automates WhatsApp Web in your browser. It is subject to "
    "WhatsApp's Terms of Service and enforcement. Ribhus does not promise "
    "account safety. You are responsible for your account. Bulk and spam "
    "sends are blocked. Every send requires explicit approval (approve / "
    "edit / cancel). Use `ribhus whatsapp kill` to halt immediately."
)


class WhatsAppPolicyError(Exception):
    """Raised when a WhatsApp action is refused by policy."""


class WhatsAppKilled(WhatsAppPolicyError):
    """Kill switch is engaged or the channel is disabled."""


@dataclass
class SendRecord:
    contact: str
    message: str
    at: float


@dataclass
class WhatsAppPolicy:
    """In-process + on-disk controls for the WhatsApp channel."""

    enabled: bool = True
    kill_path: Path | None = None
    sends_per_minute: int = 3
    sends_per_hour: int = 10
    cooldown_seconds: float = 8.0
    max_identical_contacts: int = 2
    _sends: list[SendRecord] = field(default_factory=list)

    def is_killed(self) -> bool:
        if not self.enabled:
            return True
        return bool(self.kill_path and self.kill_path.exists())

    def kill(self) -> None:
        if self.kill_path is None:
            self.enabled = False
            return
        self.kill_path.parent.mkdir(parents=True, exist_ok=True)
        self.kill_path.write_text("killed\n", encoding="utf-8")

    def resume(self) -> None:
        self.enabled = True
        if self.kill_path and self.kill_path.exists():
            self.kill_path.unlink()

    def assert_alive(self) -> None:
        if self.is_killed():
            raise WhatsAppKilled(
                "WhatsApp channel is stopped (kill switch or "
                "RIBHUS_WHATSAPP_ENABLED=false). "
                "Resume with `ribhus whatsapp resume` if you intend to continue."
            )

    def assert_can_send(self, contact: str, message: str) -> None:
        self.assert_alive()
        reason = self.refuse_reason(contact, message)
        if reason:
            raise WhatsAppPolicyError(reason)

    def refuse_reason(self, contact: object, message: object) -> str | None:
        """Return a refusal string, or None if the send is allowed by policy."""
        if isinstance(contact, (list, tuple, set, dict)):
            return "One recipient per send. Bulk / broadcast lists are not allowed."
        if isinstance(message, (list, tuple)):
            return "Send exactly one message to one contact."

        name = str(contact or "").strip()
        text = str(message or "").strip()
        if not name:
            return "A single contact name is required."
        if not text:
            return "Message is empty."

        bulk = _bulk_reason(name)
        if bulk:
            return bulk

        now = time.monotonic()
        recent = [s for s in self._sends if now - s.at < 3600]
        self._sends = recent

        if self.cooldown_seconds > 0 and recent:
            elapsed = now - recent[-1].at
            if elapsed < self.cooldown_seconds:
                wait = self.cooldown_seconds - elapsed
                return f"Cooldown: wait {wait:.0f}s before another WhatsApp send."

        last_minute = [s for s in recent if now - s.at < 60]
        if len(last_minute) >= self.sends_per_minute:
            return (
                f"Rate limit: max {self.sends_per_minute} WhatsApp send(s) per minute."
            )
        if len(recent) >= self.sends_per_hour:
            return f"Rate limit: max {self.sends_per_hour} WhatsApp send(s) per hour."

        same = {s.contact.lower() for s in recent if s.message == text}
        if name.lower() not in same and len(same) >= self.max_identical_contacts:
            return (
                "Refusing identical messages to multiple contacts (spam). "
                "Write a distinct reply per person."
            )
        return None

    def record_send(self, contact: str, message: str) -> None:
        self._sends.append(
            SendRecord(
                contact=contact.strip(),
                message=str(message).strip(),
                at=time.monotonic(),
            )
        )

    def status(self) -> dict[str, object]:
        now = time.monotonic()
        hour = [s for s in self._sends if now - s.at < 3600]
        return {
            "channel": CHANNEL_LABEL,
            "enabled": self.enabled,
            "killed": self.is_killed(),
            "sends_last_hour": len(hour),
            "sends_per_minute": self.sends_per_minute,
            "sends_per_hour": self.sends_per_hour,
            "cooldown_seconds": self.cooldown_seconds,
            "kill_path": str(self.kill_path) if self.kill_path else None,
        }


def _bulk_reason(name: str) -> str | None:
    lowered = name.lower().strip()
    if any(sep in name for sep in (",", ";", "|", "\n", "\t")):
        return "One recipient per send. Bulk / broadcast lists are not allowed."
    banned = {
        "broadcast",
        "everyone",
        "all contacts",
        "all chats",
        "spam",
    }
    if lowered in banned:
        return "Broadcast / bulk sending is not allowed."
    return None
