from __future__ import annotations

from ribhus.agent.plan_loop import (
    batch_has_non_todo,
    batch_writes_plan,
    looks_multi_step,
    plan_has_open_items,
)
from ribhus.models.base import ToolCall
from ribhus.tools.todo import TodoStore


def test_looks_multi_step_connectors():
    assert looks_multi_step(
        "Research top cafes then draft and send an email summary to a@b.com"
    )
    assert looks_multi_step("Find the docs and then open the README")
    assert looks_multi_step("Look up flights after that book the hotel")


def test_looks_multi_step_research_then_act():
    assert looks_multi_step("Research competitors and send whatsapp update")
    assert looks_multi_step("Email the team after you search for pricing")


def test_looks_multi_step_many_verbs():
    assert looks_multi_step(
        "Search the repo, read the config, then write a short summary note"
    )


def test_looks_multi_step_rejects_simple():
    assert not looks_multi_step("what is 2+2")
    assert not looks_multi_step("hi")
    assert not looks_multi_step("say hello")
    assert not looks_multi_step("")


def test_plan_has_open_items():
    store = TodoStore()
    assert not plan_has_open_items(store)
    store.write(
        [{"id": "1", "content": "a", "status": "completed"}],
        merge=False,
    )
    assert not plan_has_open_items(store)
    store.write(
        [
            {"id": "1", "content": "a", "status": "completed"},
            {"id": "2", "content": "b", "status": "pending"},
        ],
        merge=False,
    )
    assert plan_has_open_items(store)


def test_batch_plan_helpers():
    echo = ToolCall(id="1", name="echo", arguments={"text": "x"})
    todo = ToolCall(
        id="2",
        name="todo",
        arguments={
            "merge": False,
            "todos": [{"id": "1", "content": "a", "status": "pending"}],
        },
    )
    todo_read = ToolCall(id="3", name="todo", arguments={})
    assert batch_has_non_todo([echo, todo])
    assert not batch_has_non_todo([todo])
    assert batch_writes_plan([todo])
    assert not batch_writes_plan([todo_read])
    assert not batch_writes_plan([echo])
