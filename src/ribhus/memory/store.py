from __future__ import annotations

import json
import re
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

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    id UNINDEXED,
    kind UNINDEXED,
    key,
    content,
    tokenize = 'porter unicode61'
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


def _fts_query(raw: str) -> str:
    """Build a safe FTS5 MATCH query from free text."""
    tokens = re.findall(r"[A-Za-z0-9_₹]+", raw, flags=re.UNICODE)
    if not tokens:
        return ""
    # Prefix match on last token helps partial club/city names.
    parts: list[str] = []
    for i, tok in enumerate(tokens[:12]):
        if i == len(tokens) - 1 and len(tok) >= 2:
            parts.append(f'"{tok}"*')
        else:
            parts.append(f'"{tok}"')
    return " ".join(parts)


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
            self._conn.executescript(FTS_SCHEMA)
            self._conn.commit()
            self._backfill_fts()

    def _backfill_fts(self) -> None:
        count = self._conn.execute("SELECT COUNT(*) AS c FROM memories_fts").fetchone()["c"]
        mem_count = self._conn.execute("SELECT COUNT(*) AS c FROM memories").fetchone()["c"]
        if count >= mem_count:
            return
        self._conn.execute("DELETE FROM memories_fts")
        rows = self._conn.execute(
            "SELECT id, kind, key, content FROM memories WHERE disabled = 0"
        ).fetchall()
        self._conn.executemany(
            "INSERT INTO memories_fts(id, kind, key, content) VALUES(?, ?, ?, ?)",
            [(r["id"], r["kind"], r["key"] or "", r["content"]) for r in rows],
        )
        self._conn.commit()

    def _fts_upsert(self, record: MemoryRecord) -> None:
        self._conn.execute("DELETE FROM memories_fts WHERE id = ?", (record.id,))
        if not record.disabled:
            self._conn.execute(
                "INSERT INTO memories_fts(id, kind, key, content) VALUES(?, ?, ?, ?)",
                (record.id, record.kind, record.key or "", record.content),
            )

    def _fts_delete(self, memory_id: str) -> None:
        self._conn.execute("DELETE FROM memories_fts WHERE id = ?", (memory_id,))

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
            self._fts_upsert(record)
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

    def get_by_keys(
        self, keys: list[str], *, kind: MemoryKind = "semantic"
    ) -> list[MemoryRecord]:
        if not keys:
            return []
        placeholders = ",".join("?" for _ in keys)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM memories WHERE kind = ? AND disabled = 0 "
                f"AND key IN ({placeholders})",
                [kind, *keys],
            ).fetchall()
        records = [_row_to_record(r) for r in rows]
        by_key = {r.key: r for r in records if r.key}
        return [by_key[k] for k in keys if k in by_key]

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

    def search(
        self,
        query: str,
        *,
        limit: int = 12,
        kind: MemoryKind | None = None,
    ) -> list[MemoryRecord]:
        needle = query.strip()
        if not needle:
            return []
        match = _fts_query(needle)
        if match:
            sql = (
                "SELECT m.* FROM memories_fts f "
                "JOIN memories m ON m.id = f.id "
                "WHERE memories_fts MATCH ? AND m.disabled = 0"
            )
            # FTS5 table-valued: need FROM memories_fts WHERE memories_fts MATCH
            sql = (
                "SELECT m.* FROM memories_fts "
                "JOIN memories m ON m.id = memories_fts.id "
                "WHERE memories_fts MATCH ? AND m.disabled = 0"
            )
            params: list[Any] = [match]
            if kind:
                sql += " AND m.kind = ?"
                params.append(kind)
            sql += " ORDER BY rank LIMIT ?"
            params.append(int(limit))
            with self._lock:
                try:
                    rows = self._conn.execute(sql, params).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            if rows:
                return [_row_to_record(row) for row in rows]

        # Fallback LIKE
        like = f"%{needle.replace('%', '').replace('_', '')}%"
        sql = (
            "SELECT * FROM memories WHERE disabled = 0 AND "
            "(content LIKE ? OR IFNULL(key, '') LIKE ? OR metadata LIKE ?)"
        )
        params = [like, like, like]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(int(limit))
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
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
            updated = MemoryRecord(
                id=current.id,
                kind=current.kind,
                key=current.key,
                content=new_content,
                metadata=new_meta,
                disabled=new_disabled,
                created_at=current.created_at,
                updated_at=now,
            )
            self._fts_upsert(updated)
            self._conn.commit()
        return updated

    def delete(self, memory_id: str) -> None:
        if self.get(memory_id) is None:
            raise FileNotFoundError(f"Memory not found: {memory_id}")
        with self._lock:
            self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            self._fts_delete(memory_id)
            self._conn.commit()

    def delete_by_key(self, kind: MemoryKind, key: str) -> str | None:
        record = self.get_by_key(kind, key)
        if record is None:
            return None
        self.delete(record.id)
        return record.id

    def prune_kind(self, kind: MemoryKind, *, keep: int) -> int:
        """Delete oldest rows of a kind beyond `keep`. Returns number deleted."""
        keep = max(0, int(keep))
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM memories WHERE kind = ? "
                "ORDER BY updated_at DESC",
                (kind,),
            ).fetchall()
            excess = [r["id"] for r in rows[keep:]]
            for mid in excess:
                self._conn.execute("DELETE FROM memories WHERE id = ?", (mid,))
                self._fts_delete(mid)
            self._conn.commit()
        return len(excess)

    def export_all(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memories ORDER BY created_at ASC"
            ).fetchall()
        return [_row_to_record(row).model_dump() for row in rows]
