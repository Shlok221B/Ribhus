"""Epic 1A — typed task events, seq, after_seq."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ribhus.web.app import create_app
from ribhus.web.auth import get_session_token
from ribhus.web.task_store import TaskStore, normalize_event_type


def test_normalize_event_aliases() -> None:
    assert normalize_event_type("started") == "turn.started"
    assert normalize_event_type("tool_start") == "tool.started"
    assert normalize_event_type("tool_end") == "tool.finished"
    assert normalize_event_type("approval_requested") == "approval.requested"
    assert normalize_event_type("done") == "turn.completed"
    assert normalize_event_type("error") == "turn.failed"
    assert normalize_event_type("handoff_sent") == "handoff.sent"
    assert normalize_event_type("turn.started") == "turn.started"
    assert normalize_event_type("thinking") == "thinking"


def test_add_event_monotonic_seq(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.json")
    task = store.create("hello")
    a = store.add_event(task.id, "turn.started", {})
    b = store.add_event(task.id, "tool_start", {"name": "web_search"})
    c = store.add_event(task.id, "tool.finished", {"name": "web_search", "ok": True})
    assert a is not None and b is not None and c is not None
    assert a.seq == 1
    assert b.seq == 2
    assert c.seq == 3
    assert b.event_type == "tool.started"
    assert c.event_type == "tool.finished"
    assert a.event_id != b.event_id
    rows = [e.seq for e in store.get(task.id).events]  # type: ignore[union-attr]
    assert rows == [1, 2, 3]


def test_list_events_after_seq_no_duplicates(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.json")
    task = store.create("hello")
    store.add_event(task.id, "turn.started", {})
    store.add_event(task.id, "tool.started", {"name": "python"})
    store.add_event(task.id, "tool.finished", {"name": "python"})
    store.add_event(task.id, "turn.completed", {"text": "ok"})

    first = store.list_events(task.id, after_seq=0)
    assert [e.seq for e in first] == [1, 2, 3, 4]
    mid = store.list_events(task.id, after_seq=2)
    assert [e.seq for e in mid] == [3, 4]
    assert {e.event_id for e in mid}.isdisjoint({e.event_id for e in first[:2]})
    empty = store.list_events(task.id, after_seq=4)
    assert empty == []
    # Reconnect with last next_seq does not duplicate
    again = store.list_events(task.id, after_seq=mid[-1].seq)
    assert again == []


def test_legacy_events_load_with_seq(tmp_path: Path) -> None:
    path = tmp_path / "tasks.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "abc123",
                    "prompt": "old",
                    "status": "completed",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:01+00:00",
                    "events": [
                        {"ts": "t1", "event": "started", "data": {}},
                        {
                            "ts": "t2",
                            "event": "tool_end",
                            "data": {"name": "location", "result_preview": "x"},
                        },
                    ],
                    "turns": [],
                }
            ]
        ),
        encoding="utf-8",
    )
    store = TaskStore(path)
    task = store.get("abc123")
    assert task is not None
    assert len(task.events) == 2
    assert task.events[0].event_type == "turn.started"
    assert task.events[0].seq == 1
    assert task.events[1].event_type == "tool.finished"
    assert task.events[1].seq == 2
    dumped = task.events[0].to_dict()
    assert dumped["event"] == "turn.started"
    assert dumped["data"] == {}
    assert dumped["event_type"] == "turn.started"


def test_events_api_after_seq(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "ws"
    home.mkdir()
    (home / ".ribhus").mkdir()
    monkeypatch.chdir(home)
    monkeypatch.setenv("RIBHUS_WORKSPACE", str(home))
    monkeypatch.setenv("RIBHUS_API_KEY", "test-key-not-real")

    store = TaskStore(home / ".ribhus" / "tasks.json")
    app = create_app(task_store=store)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {get_session_token()}"}

    task = store.create("probe")
    store.add_event(task.id, "turn.started", {})
    store.add_event(task.id, "tool.started", {"name": "python"})
    store.add_event(task.id, "tool.finished", {"name": "python", "ok": True})

    all_rows = client.get(f"/api/tasks/{task.id}/events", headers=headers)
    assert all_rows.status_code == 200
    body = all_rows.json()
    assert body["task_id"] == task.id
    assert [e["seq"] for e in body["events"]] == [1, 2, 3]
    assert body["next_seq"] == 3
    assert body["events"][0]["event_type"] == "turn.started"
    assert body["events"][1]["event"] == "tool.started"  # legacy alias

    delta = client.get(
        f"/api/tasks/{task.id}/events",
        params={"after_seq": 1},
        headers=headers,
    )
    assert delta.status_code == 200
    dbody = delta.json()
    assert [e["seq"] for e in dbody["events"]] == [2, 3]
    assert dbody["next_seq"] == 3

    none = client.get(
        f"/api/tasks/{task.id}/events",
        params={"after_seq": 3},
        headers=headers,
    )
    assert none.json()["events"] == []
    assert none.json()["next_seq"] == 3

    missing = client.get("/api/tasks/nope/events", headers=headers)
    assert missing.status_code == 404
