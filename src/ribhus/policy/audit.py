from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class AuditLog:
    """Append-only JSONL audit trail for tool executions."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        *,
        tool: str,
        risk: str,
        arguments: dict[str, Any],
        approved: bool | None,
        result_preview: str,
        ok: bool,
    ) -> None:
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "tool": tool,
            "risk": risk,
            "arguments": _redact(arguments),
            "approved": approved,
            "ok": ok,
            "result_preview": result_preview[:500],
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")


def _redact(arguments: dict[str, Any]) -> dict[str, Any]:
    sensitive = {"password", "token", "api_key", "secret", "authorization"}
    out: dict[str, Any] = {}
    for key, value in arguments.items():
        if key.lower() in sensitive:
            out[key] = "***"
        else:
            out[key] = value
    return out
