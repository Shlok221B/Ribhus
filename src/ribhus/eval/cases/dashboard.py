from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator
from unittest.mock import patch

from ribhus.eval.harness import isolated_cwd, temp_workspace
from ribhus.eval.models import EvalCase, EvalSkip


@contextmanager
def dashboard_client() -> Iterator[tuple[Any, dict[str, str], Any]]:
    try:
        from fastapi.testclient import TestClient
    except ImportError as extra:
        raise EvalSkip("install the dashboard extra (fastapi)") from extra

    from ribhus.web.app import create_app
    from ribhus.web.auth import get_session_token
    from ribhus.web.task_store import TaskStore

    with temp_workspace() as home:
        env = {
            "RIBHUS_WORKSPACE": str(home),
            "RIBHUS_API_KEY": "test-key-not-real",
            "RIBHUS_MEMORY_ENABLED": "true",
            "RIBHUS_MCP_ENABLED": "false",
            "RIBHUS_WHATSAPP_ENABLED": "true",
            "RIBHUS_EMAIL_ENABLED": "true",
        }
        with patch.dict(os.environ, env, clear=False), isolated_cwd(home):
            store = TaskStore(home / ".ribhus" / "tasks.json")
            app = create_app(task_store=store)
            client = TestClient(app)
            headers = {"Authorization": f"Bearer {get_session_token()}"}
            yield client, headers, home


def health_unauthenticated() -> None:
    with dashboard_client() as (client, _headers, _home):
        res = client.get("/api/health")
        assert res.status_code == 200
        body = res.json()
        assert body["ok"] is True
        assert "version" in body


def config_requires_auth() -> None:
    with dashboard_client() as (client, headers, _home):
        assert client.get("/api/config").status_code == 401
        res = client.get("/api/config", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["api_key_set"] is True
        assert "test-key" not in data.get("api_key_masked", "")


def skills_list() -> None:
    with dashboard_client() as (client, headers, _home):
        res = client.get("/api/skills", headers=headers)
        assert res.status_code == 200
        names = {row["name"] for row in res.json()}
        assert names & {"company-research", "travel", "football"}


def channels_kill_resume() -> None:
    with dashboard_client() as (client, headers, home):
        res = client.get("/api/channels", headers=headers)
        assert res.status_code == 200
        assert {c["channel"] for c in res.json()} == {"whatsapp", "email"}
        kill = client.post("/api/channels/whatsapp/kill", headers=headers)
        assert kill.status_code == 200
        assert kill.json()["killed"] is True
        assert (home / ".ribhus" / "whatsapp.killed").exists()
        resume = client.post("/api/channels/whatsapp/resume", headers=headers)
        assert resume.status_code == 200
        assert resume.json()["killed"] is False


def memory_add_list() -> None:
    with dashboard_client() as (client, headers, _home):
        add = client.post(
            "/api/memory",
            headers=headers,
            json={"content": "Prefer Hinglish replies", "key": "language"},
        )
        assert add.status_code == 200
        assert add.json()["key"] == "language"
        listed = client.get("/api/memory", headers=headers)
        assert listed.status_code == 200
        assert any(row["key"] == "language" for row in listed.json())


CASES = [
    EvalCase("dashboard-health", "dashboard", "GET /api/health", "Health is public", health_unauthenticated),
    EvalCase("dashboard-config-auth", "dashboard", "GET /api/config", "Config requires bearer token", config_requires_auth),
    EvalCase("dashboard-skills", "dashboard", "GET /api/skills", "Skills list includes bundled", skills_list),
    EvalCase("dashboard-channels", "dashboard", "POST /api/channels", "WhatsApp kill/resume", channels_kill_resume),
    EvalCase("dashboard-memory", "dashboard", "POST /api/memory", "Memory add/list via API", memory_add_list),
]
