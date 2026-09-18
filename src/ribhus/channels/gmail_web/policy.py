from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

CHANNEL_LABEL = "Gmail Web (browser automation — not the Gmail API)"

TOS_WARNING = (
    "This channel automates Gmail in your browser. It is subject to Google's "
    "Terms of Service. Ribhus does not promise account safety. Bulk and spam "
    "sends are blocked. Every send requires explicit approval (approve / "
    "edit / cancel). Use `ribhus email kill` to halt immediately."
)


class EmailPolicyError(Exception):
    """Raised when a Gmail action is refused by policy."""


class EmailKilled(EmailPolicyError):
    """Kill switch is engaged or the channel is disabled."""


@dataclass
class SendRecord:
    to: str
    subject: str
    at: float


@dataclass
class EmailPolicy:
    enabled: bool = True
    kill_path: Path | None = None
    sends_per_minute: int = 3
    sends_per_hour: int = 15
    cooldown_seconds: float = 8.0
    _sends: list[SendRecord] = field(default_factory=list)

    def is_killed(self) -> bool:
        if not self.enabled:
            return True
        return bool(self.kill_path and self.kill_path.exists())

    def is_active(self) -> bool:
        return not self.is_killed()

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
        if not self.is_active():
            raise EmailKilled(
                "Email/Gmail channel is stopped (kill switch or "
                "RIBHUS_EMAIL_ENABLED=false). "
                "Resume with `ribhus email resume` if you intend to continue."
            )

    def refuse_reason(self, to: str, subject: str, body: str) -> str | None:
        to = (to or "").strip()
        subject = (subject or "").strip()
        body = (body or "").strip()
        if not body:
            return "body is required"
        if len(body) > 50_000:
            return "body too long (max 50k chars)"
        if to and ("," in to or ";" in to):
            return "only one recipient allowed (no bulk)"
        if to:
            if "@" not in to or to.startswith("@") or to.endswith("@"):
                return "recipient must look like an email address (or leave empty for reply-in-thread)"
            local, _, domain = to.partition("@")
            if not local or "." not in domain:
                return "recipient must look like an email address (or leave empty for reply-in-thread)"

        now = time.time()
        recent = [s for s in self._sends if now - s.at < 3600]
        self._sends = recent
        if self.cooldown_seconds > 0 and recent:
            last = max(s.at for s in recent)
            if now - last < self.cooldown_seconds:
                wait = self.cooldown_seconds - (now - last)
                return f"cooldown: wait {wait:.0f}s before another send"
        minute = [s for s in recent if now - s.at < 60]
        if len(minute) >= self.sends_per_minute:
            return f"rate limit: max {self.sends_per_minute} sends/minute"
        if len(recent) >= self.sends_per_hour:
            return f"rate limit: max {self.sends_per_hour} sends/hour"
        return None

    def assert_can_send(self, to: str, subject: str, body: str) -> None:
        self.assert_alive()
        reason = self.refuse_reason(to, subject, body)
        if reason:
            raise EmailPolicyError(reason)

    def record_send(self, to: str, subject: str) -> None:
        self._sends.append(SendRecord(to=to or "(thread)", subject=subject, at=time.time()))

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "active": self.is_active(),
            "killed": self.is_killed(),
            "kill_path": str(self.kill_path) if self.kill_path else None,
            "sends_last_hour": len(
                [s for s in self._sends if time.time() - s.at < 3600]
            ),
            "sends_per_minute": self.sends_per_minute,
            "sends_per_hour": self.sends_per_hour,
            "cooldown_seconds": self.cooldown_seconds,
        }
