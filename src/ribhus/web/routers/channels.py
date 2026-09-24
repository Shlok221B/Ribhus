from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException

from ribhus.channels.gmail_web.policy import EmailPolicy
from ribhus.channels.whatsapp_web.policy import WhatsAppPolicy
from ribhus.config import get_settings
from ribhus.web.auth import AuthDep

router = APIRouter(prefix="/api/channels", tags=["channels"])


def _whatsapp_status() -> dict[str, Any]:
    settings = get_settings()
    policy = WhatsAppPolicy(
        enabled=settings.whatsapp_enabled,
        kill_path=settings.ribhus_dir / "whatsapp.killed",
        sends_per_minute=settings.whatsapp_rate_limit,
        sends_per_hour=settings.whatsapp_max_per_hour,
        cooldown_seconds=settings.whatsapp_cooldown,
    )
    st = policy.status()
    return {
        "channel": "whatsapp",
        "enabled": bool(st.get("enabled", settings.whatsapp_enabled)),
        "killed": bool(st.get("killed", policy.is_killed())),
        "headed": settings.whatsapp_headed,
        "profile_dir": str(settings.ribhus_dir / "whatsapp_profile"),
        "kill_path": str(settings.ribhus_dir / "whatsapp.killed"),
        "note": (
            "Browser automation of WhatsApp Web — not the official API. "
            "Login via: ribhus whatsapp status --check-login"
        ),
    }


def _email_status() -> dict[str, Any]:
    settings = get_settings()
    policy = EmailPolicy(
        enabled=settings.email_enabled,
        kill_path=settings.ribhus_dir / "email.killed",
        sends_per_minute=settings.email_rate_limit,
        sends_per_hour=settings.email_max_per_hour,
        cooldown_seconds=settings.email_cooldown,
    )
    st = policy.status()
    return {
        "channel": "email",
        "enabled": bool(st.get("enabled", settings.email_enabled)),
        "killed": bool(st.get("killed", policy.is_killed())),
        "headed": settings.email_headed,
        "profile_dir": str(settings.ribhus_dir / "gmail_profile"),
        "kill_path": str(settings.ribhus_dir / "email.killed"),
        "note": (
            "Browser automation of Gmail — not the Gmail API. "
            "Login via: ribhus email status --check-login"
        ),
    }


@router.get("")
def list_channels(_: AuthDep) -> list[dict[str, Any]]:
    return [_whatsapp_status(), _email_status()]


@router.post("/{channel}/{action}")
def channel_action(
    channel: Literal["whatsapp", "email"],
    action: Literal["kill", "resume"],
    _: AuthDep,
) -> dict[str, Any]:
    settings = get_settings()
    if channel == "whatsapp":
        policy = WhatsAppPolicy(
            enabled=settings.whatsapp_enabled,
            kill_path=settings.ribhus_dir / "whatsapp.killed",
            sends_per_minute=settings.whatsapp_rate_limit,
            sends_per_hour=settings.whatsapp_max_per_hour,
            cooldown_seconds=settings.whatsapp_cooldown,
        )
        if action == "kill":
            policy.kill()
        else:
            policy.resume()
        return _whatsapp_status()
    if channel == "email":
        policy = EmailPolicy(
            enabled=settings.email_enabled,
            kill_path=settings.ribhus_dir / "email.killed",
            sends_per_minute=settings.email_rate_limit,
            sends_per_hour=settings.email_max_per_hour,
            cooldown_seconds=settings.email_cooldown,
        )
        if action == "kill":
            policy.kill()
        else:
            policy.resume()
        return _email_status()
    raise HTTPException(status_code=404, detail="Unknown channel")
