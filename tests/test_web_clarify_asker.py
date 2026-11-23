from __future__ import annotations

import threading
from pathlib import Path

from ribhus.web.clarify_asker import make_task_clarify_asker
from ribhus.web.task_store import TaskStore


def test_clarify_asker_returns_choice(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.json")
    task = store.create("Message these 12 hostels on WhatsApp")
    asker = make_task_clarify_asker(store, task.id)
    choice = "Draft buttons (safer for lists — you click Send in WhatsApp)"

    def answer() -> None:
        for _ in range(50):
            row = store.get(task.id)
            if row and row.pending_approval and row.pending_approval.tool == "clarify":
                store.resolve_approval(
                    task.id, decision="edit", edited_text=choice
                )
                return
            threading.Event().wait(0.02)
        raise AssertionError("clarify approval never appeared")

    worker = threading.Thread(target=answer, daemon=True)
    worker.start()
    result = asker(
        "How should I deliver these WhatsApp messages?",
        [
            choice,
            "Auto-send via WhatsApp Web (Playwright — slower, account risk)",
        ],
    )
    worker.join(timeout=5)
    assert result == choice
    refreshed = store.get(task.id)
    assert refreshed is not None
    assert refreshed.pending_approval is None


def test_clarify_asker_cancel_on_deny(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.json")
    task = store.create("outreach")
    asker = make_task_clarify_asker(store, task.id)

    def deny() -> None:
        for _ in range(50):
            row = store.get(task.id)
            if row and row.pending_approval:
                store.resolve_approval(task.id, decision="deny")
                return
            threading.Event().wait(0.02)

    worker = threading.Thread(target=deny, daemon=True)
    worker.start()
    assert asker("Pick a mode?", ["A", "B"]) == "cancel"
    worker.join(timeout=5)
