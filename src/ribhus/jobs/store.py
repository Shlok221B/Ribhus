"""Local job-hunt files under `.ribhus/job_hunt/`."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ribhus.jobs.errors import JobHuntError

_MAX_TEX_CHARS = 400_000


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class JobStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def resume_path(self) -> Path:
        return self.root / "resume.tex"

    @property
    def apps_dir(self) -> Path:
        return self.root / "apps"

    def save_resume(self, tex: str) -> dict[str, Any]:
        text = (tex or "").strip()
        if "\\documentclass" not in text:
            raise JobHuntError("That file is not a LaTeX resume (missing \\documentclass).")
        if len(text) > _MAX_TEX_CHARS:
            raise JobHuntError("Resume is too large.")
        self.root.mkdir(parents=True, exist_ok=True)
        self.resume_path.write_text(text + "\n", encoding="utf-8")
        return {
            "saved": True,
            "chars": len(text),
            "path": str(self.resume_path),
        }

    def read_resume(self) -> str:
        if not self.resume_path.is_file():
            raise JobHuntError("Save your LaTeX resume before preparing an application.")
        return self.resume_path.read_text(encoding="utf-8")

    def resume_saved(self) -> bool:
        return self.resume_path.is_file() and "\\documentclass" in self.resume_path.read_text(
            encoding="utf-8"
        )

    def list_applications(self) -> list[dict[str, Any]]:
        if not self.apps_dir.is_dir():
            return []
        rows: list[dict[str, Any]] = []
        for meta in self.apps_dir.glob("*/meta.json"):
            try:
                rows.append(json.loads(meta.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        return rows

    def get(self, application_id: str) -> dict[str, Any]:
        path = self._meta_path(application_id)
        if not path.is_file():
            raise JobHuntError("Application not found.")
        return json.loads(path.read_text(encoding="utf-8"))

    def create(self, record: dict[str, Any]) -> dict[str, Any]:
        application_id = uuid.uuid4().hex[:12]
        record = {
            **record,
            "id": application_id,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        folder = self._folder(application_id)
        folder.mkdir(parents=True, exist_ok=True)
        self._write(application_id, record)
        return record

    def update(self, application_id: str, **fields: Any) -> dict[str, Any]:
        record = self.get(application_id)
        record.update(fields)
        record["updated_at"] = utc_now()
        self._write(application_id, record)
        return record

    def write_tex(self, application_id: str, tex: str) -> Path:
        path = self._folder(application_id) / "resume.tex"
        path.write_text(tex, encoding="utf-8")
        return path

    def folder(self, application_id: str) -> Path:
        return self._folder(application_id)

    def pdf_path(self, record: dict[str, Any]) -> Path:
        name = str(record.get("pdf_file") or "")
        if not name or "/" in name or "\\" in name:
            raise JobHuntError("This application has no PDF yet.")
        path = self._folder(str(record["id"])) / name
        if not path.is_file():
            raise JobHuntError("PDF file is missing. Prepare the application again.")
        return path

    def _folder(self, application_id: str) -> Path:
        safe = _safe_id(application_id)
        return self.apps_dir / safe

    def _meta_path(self, application_id: str) -> Path:
        return self._folder(application_id) / "meta.json"

    def _write(self, application_id: str, record: dict[str, Any]) -> None:
        path = self._meta_path(application_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def _safe_id(application_id: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{12}", application_id or ""):
        raise JobHuntError("Application not found.")
    return application_id
