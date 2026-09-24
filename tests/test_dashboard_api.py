"""Dashboard API smoke tests (real FastAPI + temp HERMES-style home via workspace)."""

from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ribhus.web.app import create_app
from ribhus.web.auth import get_session_token
from ribhus.web.task_store import TaskStore


@pytest.fixture
def dashboard_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "ws"
    home.mkdir()
    (home / ".ribhus").mkdir()
    monkeypatch.chdir(home)
    monkeypatch.setenv("RIBHUS_WORKSPACE", str(home))
    monkeypatch.setenv("RIBHUS_API_KEY", "test-key-not-real")
    monkeypatch.setenv("RIBHUS_MEMORY_ENABLED", "true")
    monkeypatch.setenv("RIBHUS_MCP_ENABLED", "false")
    monkeypatch.setenv("RIBHUS_WHATSAPP_ENABLED", "true")
    monkeypatch.setenv("RIBHUS_EMAIL_ENABLED", "true")
    store = TaskStore(home / ".ribhus" / "tasks.json")
    app = create_app(task_store=store)
    client = TestClient(app)
    token = get_session_token()
    headers = {"Authorization": f"Bearer {token}"}
    return client, headers, home


def test_health_unauthenticated(dashboard_env):
    client, _headers, _home = dashboard_env
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert "version" in body


def test_config_requires_auth(dashboard_env):
    client, headers, _home = dashboard_env
    assert client.get("/api/config").status_code == 401
    res = client.get("/api/config", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["api_key_set"] is True
    assert "test-key" not in data.get("api_key_masked", "")
    assert data["api_key_masked"] != "test-key-not-real"


def test_skills_list(dashboard_env):
    client, headers, _home = dashboard_env
    res = client.get("/api/skills", headers=headers)
    assert res.status_code == 200
    skills = res.json()
    assert isinstance(skills, list)
    names = {s["name"] for s in skills}
    # Bundled / workspace skills should be discoverable from the package.
    assert len(names) >= 1


def test_channels_kill_resume(dashboard_env):
    client, headers, home = dashboard_env
    res = client.get("/api/channels", headers=headers)
    assert res.status_code == 200
    channels = res.json()
    assert {c["channel"] for c in channels} == {"whatsapp", "email"}

    kill = client.post("/api/channels/whatsapp/kill", headers=headers)
    assert kill.status_code == 200
    assert kill.json()["killed"] is True
    assert (home / ".ribhus" / "whatsapp.killed").exists()

    resume = client.post("/api/channels/whatsapp/resume", headers=headers)
    assert resume.status_code == 200
    assert resume.json()["killed"] is False


def test_memory_add_list_forget(dashboard_env):
    client, headers, _home = dashboard_env
    add = client.post(
        "/api/memory",
        headers=headers,
        json={"content": "Prefer Hinglish replies", "key": "language"},
    )
    assert add.status_code == 200
    assert add.json()["key"] == "language"

    listed = client.get("/api/memory", headers=headers)
    assert listed.status_code == 200
    assert any(r["key"] == "language" for r in listed.json())

    forgotten = client.delete("/api/memory/language", headers=headers)
    assert forgotten.status_code == 200


def test_task_create_and_list(dashboard_env, monkeypatch: pytest.MonkeyPatch):
    client, headers, _home = dashboard_env

    async def _noop_run(store, task_id: str) -> None:
        store.update(task_id, status="completed", result="ok")

    monkeypatch.setattr("ribhus.web.routers.tasks.run_task", _noop_run)

    created = client.post(
        "/api/tasks",
        headers=headers,
        json={"prompt": "Say hello"},
    )
    assert created.status_code == 200
    task = created.json()
    assert task["prompt"] == "Say hello"
    assert task["id"]

    listed = client.get("/api/tasks", headers=headers)
    assert listed.status_code == 200
    assert any(t["id"] == task["id"] for t in listed.json())

    got = client.get(f"/api/tasks/{task['id']}", headers=headers)
    assert got.status_code == 200


def test_task_store_approval_roundtrip(tmp_path: Path):
    store = TaskStore(tmp_path / "tasks.json")
    task = store.create("send a message")
    approval_id, event = store.begin_approval(
        task.id,
        tool="whatsapp_send",
        risk="critical",
        arguments={"contact": "Rahul", "message": "hi"},
    )
    current = store.get(task.id)
    assert current is not None
    assert current.status == "awaiting_approval"
    assert current.pending_approval is not None
    assert current.pending_approval.id == approval_id

    updated = store.resolve_approval(task.id, decision="approve")
    assert updated is not None
    assert updated.status == "running"
    assert updated.pending_approval is None
    assert event.is_set()
    decision, edited = store.wait_approval_result(approval_id)
    assert decision == "approve"
    assert edited is None
