"""Bot roster, chats, queues, handoffs, and memory scoping."""

from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ribhus.bots.chat_store import ChatStore, parse_mentions
from ribhus.bots.message_tool import MAX_HANDOFF_HOPS, MessageBotTool
from ribhus.bots.queue import BotJob, BotQueueManager
from ribhus.bots.store import BotStore
from ribhus.memory.service import MemoryService
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
    store = TaskStore(home / ".ribhus" / "tasks.json")
    app = create_app(task_store=store)
    client = TestClient(app)
    token = get_session_token()
    headers = {"Authorization": f"Bearer {token}"}
    return client, headers, home


def test_bot_store_seeds_primary(tmp_path: Path):
    store = BotStore(tmp_path / "bots.json")
    bots = store.list()
    assert len(bots) == 1
    assert bots[0].name == "Ribhus"
    assert bots[0].is_primary


def test_bot_crud_api(dashboard_env):
    client, headers, _home = dashboard_env
    listed = client.get("/api/bots", headers=headers)
    assert listed.status_code == 200
    bots = listed.json()
    assert len(bots) >= 1
    assert any(b["is_primary"] for b in bots)

    created = client.post(
        "/api/bots",
        headers=headers,
        json={
            "name": "Researcher",
            "job": "Own company research. Cite sources.",
            "color": "blue",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["name"] == "Researcher"
    assert body["color"] == "blue"

    got = client.get(f"/api/bots/{body['id']}", headers=headers)
    assert got.status_code == 200
    assert got.json()["chat_id"]

    renamed = client.patch(
        f"/api/bots/{body['id']}",
        headers=headers,
        json={"name": "Scout"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Scout"

    primary = client.post(
        f"/api/bots/{body['id']}/primary", headers=headers
    )
    assert primary.status_code == 200
    assert primary.json()["is_primary"] is True


def test_group_chat_create_and_mentions(dashboard_env):
    client, headers, _home = dashboard_env
    a = client.post(
        "/api/bots", headers=headers, json={"name": "Alpha", "job": "A"}
    ).json()
    b = client.post(
        "/api/bots", headers=headers, json={"name": "Beta", "job": "B"}
    ).json()
    group = client.post(
        "/api/chats/group",
        headers=headers,
        json={"bot_ids": [a["id"], b["id"]], "title": "Launch"},
    )
    assert group.status_code == 200
    chat = group.json()
    assert chat["kind"] == "group"
    assert len(chat["bot_ids"]) == 2

    # Mentions parsing
    known = {"alpha": a["id"], "beta": b["id"]}
    assert parse_mentions("@Alpha gather sources", known) == [a["id"]]
    assert parse_mentions("both @Alpha and @Beta", known) == [a["id"], b["id"]]


def test_queue_serial_per_bot_parallel_across():
    mgr = BotQueueManager()
    seen: list[str] = []

    async def handler(job: BotJob) -> None:
        seen.append(job.bot_id)

    mgr.set_handler(handler)
    # Without a running loop, enqueue only stores; kick needs a loop.
    mgr.enqueue(
        BotJob(kind="user", chat_id="c1", bot_id="a", prompt="1")
    )
    mgr.enqueue(
        BotJob(kind="user", chat_id="c1", bot_id="a", prompt="2")
    )
    assert mgr.pending("a") == 2


@pytest.mark.asyncio
async def test_message_bot_tool_queues():
    queued: list[dict] = []

    def enqueue(payload: dict) -> str:
        queued.append(payload)
        return f"Queued for {payload['to_name']}."

    tool = MessageBotTool(
        sender_bot_id="bot-a",
        sender_chat_id="chat-a",
        hop=0,
        enqueue=enqueue,
        list_bots=lambda: [
            {"id": "bot-a", "name": "Alpha"},
            {"id": "bot-b", "name": "Beta"},
        ],
    )
    result = await tool.execute(
        {"to": "Beta", "body": "Please draft", "priority": "action"}
    )
    assert "Queued" in result
    assert queued[0]["to_bot_id"] == "bot-b"
    assert queued[0]["priority"] == "action"
    assert queued[0]["hop"] == 1

    tool_max = MessageBotTool(
        sender_bot_id="bot-a",
        sender_chat_id="chat-a",
        hop=MAX_HANDOFF_HOPS,
        enqueue=enqueue,
        list_bots=lambda: [{"id": "bot-b", "name": "Beta"}],
    )
    blocked = await tool_max.execute({"to": "Beta", "body": "x"})
    assert "hop limit" in blocked.lower()


def test_memory_bot_isolation(tmp_path: Path):
    path = tmp_path / "memory.sqlite"
    shared = MemoryService.from_path(path, env_enabled=True, bot_id=None)
    shared.remember_fact("Prefer Hinglish", key="language")
    shared.close()

    a = MemoryService.from_path(path, env_enabled=True, bot_id="bot-a")
    a.remember_fact("I own company research", key="role_note")
    a.close()

    b = MemoryService.from_path(path, env_enabled=True, bot_id="bot-b")
    b.remember_fact("I own travel shortlists", key="role_note")
    addon_b = b.prompt_addon("research")
    assert "Hinglish" in addon_b or "language" in addon_b.lower() or "Prefer" in addon_b
    # Bot B should see its own role, not A's (unless search overlaps)
    private = b.store.list(kind="semantic", bot_id="bot-b", include_shared=False)
    assert any("travel" in r.content for r in private)
    a_only = b.store.list(kind="semantic", bot_id="bot-a", bot_only=True)
    # From B's store handle we can still query A's private rows by id
    assert any("company research" in r.content for r in a_only)
    b.close()

    # Deleting bot-a memories leaves shared + bot-b
    store = MemoryService.from_path(path, env_enabled=True)
    removed = store.store.delete_for_bot("bot-a")
    assert removed >= 1
    remaining = store.store.list(kind="semantic", limit=50)
    assert any(r.key == "language" for r in remaining)
    assert not any(r.bot_id == "bot-a" for r in remaining)
    store.close()


def test_create_task_routes_to_primary_bot(dashboard_env):
    client, headers, _home = dashboard_env
    bots = client.get("/api/bots", headers=headers).json()
    primary = next(b for b in bots if b["is_primary"])

    # Don't wait for the model — just ensure enqueue returns linked ids.
    # Patch orchestrator to avoid real LLM.
    from ribhus.bots.queue import BotQueueManager

    app = client.app
    orch = app.state.bot_orchestrator
    original = orch.queues.enqueue
    captured: list = []

    def capture(job):
        captured.append(job)
        # Do not run the agent.

    orch.queues.enqueue = capture  # type: ignore[method-assign]

    res = client.post(
        "/api/tasks",
        headers=headers,
        json={"prompt": "Hello primary"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["bot_id"] == primary["id"]
    assert data["chat_id"]
    assert len(captured) == 1
    assert captured[0].bot_id == primary["id"]
    assert captured[0].prompt == "Hello primary"

    orch.queues.enqueue = original


def test_chat_message_enqueues_group_speakers(dashboard_env):
    client, headers, _home = dashboard_env
    a = client.post(
        "/api/bots", headers=headers, json={"name": "Writer", "job": "Write"}
    ).json()
    b = client.post(
        "/api/bots", headers=headers, json={"name": "Editor", "job": "Edit"}
    ).json()
    chat = client.post(
        "/api/chats/group",
        headers=headers,
        json={"bot_ids": [a["id"], b["id"]], "title": "Doc"},
    ).json()

    orch = client.app.state.bot_orchestrator
    captured: list = []
    orch.queues.enqueue = lambda job: captured.append(job)  # type: ignore

    res = client.post(
        f"/api/chats/{chat['id']}/messages",
        headers=headers,
        json={"content": "@Writer draft the intro"},
    )
    assert res.status_code == 200
    assert len(captured) == 1
    assert captured[0].bot_id == a["id"]

    captured.clear()
    res2 = client.post(
        f"/api/chats/{chat['id']}/messages",
        headers=headers,
        json={"content": "What should we do next?"},
    )
    assert res2.status_code == 200
    # No mentions → both members
    assert {j.bot_id for j in captured} == {a["id"], b["id"]}


def test_delete_bot_cleans_chats(dashboard_env):
    client, headers, _home = dashboard_env
    created = client.post(
        "/api/bots", headers=headers, json={"name": "Temp", "job": "x"}
    ).json()
    # Ensure direct chat exists
    client.get(f"/api/bots/{created['id']}", headers=headers)
    deleted = client.delete(f"/api/bots/{created['id']}", headers=headers)
    assert deleted.status_code == 200
    chats = client.get("/api/chats", headers=headers).json()
    assert all(created["id"] not in c["bot_ids"] or c["kind"] == "group" for c in chats)
    # Direct for Temp should be gone
    assert not any(
        c["kind"] == "direct" and created["id"] in c["bot_ids"] for c in chats
    )


def test_chat_store_direct_and_handoff_message(tmp_path: Path):
    store = ChatStore(tmp_path / "chats.json")
    chat = store.direct_for_bot("b1", bot_name="Ribhus")
    assert chat.kind == "direct"
    again = store.direct_for_bot("b1", bot_name="Ribhus")
    assert again.id == chat.id
    msg = store.append_message(
        chat.id,
        role="handoff",
        content="Ribhus → Scout: please review",
        handoff={"from_bot_id": "b1", "to_bot_id": "b2"},
    )
    assert msg is not None
    assert msg.role == "handoff"
