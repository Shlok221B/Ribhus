"""Dashboard clarify asker — reuses the task approval wait UI."""

from __future__ import annotations

from typing import Any

from ribhus.web.task_store import TaskStore


def make_task_clarify_asker(store: TaskStore, task_id: str):
    """Block the agent thread until the user answers via the approval card."""

    def asker(question: str, choices: list[str] | None) -> str:
        payload: dict[str, Any] = {
            "question": question,
            "choices": list(choices or []),
        }
        approval_id, _event = store.begin_approval(
            task_id,
            tool="clarify",
            risk="low",
            arguments=payload,
        )
        store.add_event(
            task_id,
            "approval.requested",
            {
                "tool": "clarify",
                "risk": "low",
                "approval_id": approval_id,
                "question": question[:240],
            },
        )
        decision, edited = store.wait_approval_result(approval_id)
        if decision == "deny":
            store.add_event(
                task_id,
                "approval.resolved",
                {"tool": "clarify", "allowed": False, "decision": "deny"},
            )
            return "cancel"
        answer = (edited or "").strip()
        if decision == "edit" and answer:
            store.add_event(
                task_id,
                "approval.resolved",
                {"tool": "clarify", "allowed": True, "decision": "edit"},
            )
            return answer
        if decision == "approve":
            # Approve with no edit → first choice when only one exists.
            if choices and len(choices) == 1:
                store.add_event(
                    task_id,
                    "approval.resolved",
                    {"tool": "clarify", "allowed": True, "decision": "approve"},
                )
                return choices[0]
            if answer:
                store.add_event(
                    task_id,
                    "approval.resolved",
                    {"tool": "clarify", "allowed": True, "decision": "approve"},
                )
                return answer
        store.add_event(
            task_id,
            "approval.resolved",
            {"tool": "clarify", "allowed": False, "decision": decision},
        )
        return "cancel"

    return asker
