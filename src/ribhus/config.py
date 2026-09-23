from __future__ import annotations

import os
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ribhus.policy.levels import RiskLevel


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RIBHUS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    vision_model: str = ""  # empty = same as model; needs vision support
    workspace: Path = Path.cwd()
    max_iterations: int = 15
    tool_timeout_seconds: float = 60.0

    # Permissions
    auto_approve: bool = False
    approve_at: str = "high"  # low|medium|high|critical

    # Browser
    browser_headed: bool = False
    browser_allowlist: str = ""  # comma-separated hosts; empty = allow all
    browser_rate_limit: int = 30
    # Attach to a running Chromium-family browser (e.g. http://127.0.0.1:9222)
    browser_cdp_url: str = ""

    # WhatsApp Web channel (browser automation — not the official API)
    whatsapp_enabled: bool = True
    whatsapp_headed: bool = True  # QR login needs a visible window
    whatsapp_login_timeout: float = 120.0
    whatsapp_rate_limit: int = 3  # sends per minute
    whatsapp_max_per_hour: int = 10
    whatsapp_cooldown: float = 8.0
    # Note to Self inbox listen (ribhus whatsapp listen)
    whatsapp_inbox_chat: str = ""  # empty = try Message yourself / aliases
    whatsapp_listen_interval: float = 3.0
    whatsapp_inbox_reply_max: int = 1500

    # Memory (Phase 5) — local SQLite under .ribhus/memory.sqlite
    memory_enabled: bool = True

    # MCP client — load servers from .ribhus/mcp.json when enabled
    mcp_enabled: bool = True
    mcp_config: str = ""  # optional override path; empty = .ribhus/mcp.json

    # Gmail Web channel (browser automation — not the Gmail API)
    email_enabled: bool = True
    email_headed: bool = True  # Google sign-in needs a visible window
    email_login_timeout: float = 180.0
    email_rate_limit: int = 3
    email_max_per_hour: int = 15
    email_cooldown: float = 8.0

    @field_validator("workspace", mode="before")
    @classmethod
    def _workspace_path(cls, value: object) -> Path:
        return Path(value) if value else Path.cwd()

    @property
    def approve_at_level(self) -> RiskLevel:
        return RiskLevel.parse(self.approve_at)

    @property
    def browser_allowlist_hosts(self) -> list[str]:
        if not self.browser_allowlist.strip():
            return []
        return [part.strip() for part in self.browser_allowlist.split(",") if part.strip()]

    @property
    def effective_vision_model(self) -> str:
        return (self.vision_model or self.model).strip() or self.model

    @property
    def ribhus_dir(self) -> Path:
        return self.workspace / ".ribhus"


def get_settings() -> Settings:
    settings = Settings()
    if not settings.api_key:
        settings.api_key = os.getenv("OPENAI_API_KEY", "")
    return settings
