"""Existing memory.sqlite files without bot_id must migrate cleanly."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ribhus.memory.store import MemoryStore


def test_migrates_legacy_memories_table(tmp_path: Path) -> None:
    db = tmp_path / "memory.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            key TEXT,
            content TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            disabled INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX idx_memories_kind_key
            ON memories(kind, key) WHERE key IS NOT NULL;
        INSERT INTO memories VALUES (
            'sem_1', 'semantic', 'language', 'Prefer Hinglish', '{}', 0, 't', 't'
        );
        """
    )
    conn.commit()
    conn.close()

    store = MemoryStore(db)
    cols = {
        str(r["name"])
        for r in store._conn.execute("PRAGMA table_info(memories)").fetchall()
    }
    assert "bot_id" in cols
    rows = store.get_by_keys(["language"], shared_only=True)
    assert len(rows) == 1
    assert rows[0].content == "Prefer Hinglish"
    store.insert("semantic", "Owns research", key="role_note", bot_id="bot-a")
    private = store.get_by_key("semantic", "role_note", bot_id="bot-a")
    assert private is not None
    assert private.bot_id == "bot-a"
    store.close()
