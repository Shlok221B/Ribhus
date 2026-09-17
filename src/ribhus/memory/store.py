from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ribhus.memory.models import KINDS, MemoryKind, MemoryRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    key TEXT,
    content TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    disabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_kind_key
    ON memories(kind, key) WHERE key IS NOT NULL;
CREATE TABLE IF NOT EXISTS memory_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_id(kind: str) -> str:
    prefix = {"short_term": "st", "episodic": "epi", "semantic": "sem"}.get(kind, "mem")
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
    raw_meta = row["metadata"] or "{}"
    try:
        metadata = json.loads(raw_meta)
    except json.JSONDecodeError:
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    return MemoryRecord(
        id=row["id"],
        kind=row["kind"],
        key=row["key"],
        content=row["content"],
        metadata=metadata,
        disabled=bool(row["disabled"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class MemoryStore:
    """SQLite persistence for Ribhus memory (local file under .ribhus/)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def get_setting(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM memory_settings WHERE key = ?", (key,)
            ).fetchone()
        return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO memory_settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._conn.commit()

    def insert(
        self,
        kind: MemoryKind,
        content: str,
        *,
        key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord:
        if kind not in KINDS:
            raise ValueError(f"Unknown memory kind: {kind}")
        now = _now()
        record = MemoryRecord(
            id=_new_id(kind),
            kind=kind,
            key=key,
            content=content,
            metadata=metadata or {},
            disabled=False,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO memories(id, kind, key, content, metadata, disabled, "
                "created_at, updated_at) VALUES(?, ?, ?, ?, ?, 0, ?, ?)",
                (
                    record.id,
                    record.kind,
                    record.key,
                    record.content,
                    json.dumps(record.metadata),
                    record.created_at,
                    record.updated_at,
                ),
            )
            self._conn.commit()
        return record

    def upsert_by_key(
        self,
        kind: MemoryKind,
        key: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord:
        existing = self.get_by_key(kind, key)
        if existing is None:
            return self.insert(kind, content, key=key, metadata=metadata)
        return self.update(existing.id, content=content, metadata=metadata)

    def get(self, memory_id: str) -> MemoryRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
        return _row_to_record(row) if row else None

    def get_by_key(self, kind: MemoryKind, key: str) -> MemoryRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM memories WHERE kind = ? AND key = ?", (kind, key)
            ).fetchone()
        return _row_to_record(row) if row else None

    def list(
        self,
        *,
        kind: MemoryKind | None = None,
        include_disabled: bool = False,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        sql = "SELECT * FROM memories WHERE 1=1"
        params: list[Any] = []
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if not include_disabled:
            sql += " AND disabled = 0"
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(int(limit))
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_record(row) for row in rows]

    def search(self, query: str, *, limit: int = 12) -> list[MemoryRecord]:
        needle = query.strip().replace("%", "").replace("_", "")
        if not needle:
            return []
        like = f"%{needle}%"
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE disabled = 0 AND "
                "(content LIKE ? OR IFNULL(key, '') LIKE ? OR metadata LIKE ?) "
                "ORDER BY updated_at DESC LIMIT ?",
                (like, like, like, int(limit)),
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def update(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
        disabled: bool | None = None,
    ) -> MemoryRecord:
        current = self.get(memory_id)
        if current is None:
            raise FileNotFoundError(f"Memory not found: {memory_id}")
        new_content = current.content if content is None else content
        new_meta = current.metadata if metadata is None else metadata
        new_disabled = current.disabled if disabled is None else disabled
        now = _now()
        with self._lock:
            self._conn.execute(
                "UPDATE memories SET content = ?, metadata = ?, disabled = ?, "
                "updated_at = ? WHERE id = ?",
                (
                    new_content,
                    json.dumps(new_meta),
                    1 if new_disabled else 0,
                    now,
                    memory_id,
                ),
            )
            self._conn.commit()
        updated = self.get(memory_id)
        assert updated is not None
        return updated

    def delete(self, memory_id: str) -> None:
        if self.get(memory_id) is None:
            raise FileNotFoundError(f"Memory not found: {memory_id}")
        with self._lock:
            self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            self._conn.commit()

    def export_all(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memories ORDER BY created_at ASC"
            ).fetchall()
        return [_row_to_record(row).model_dump() for row in rows]
