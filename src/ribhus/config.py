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
    def ribhus_dir(self) -> Path:
        return self.workspace / ".ribhus"


def get_settings() -> Settings:
    settings = Settings()
    if not settings.api_key:
        settings.api_key = os.getenv("OPENAI_API_KEY", "")
    return settings
