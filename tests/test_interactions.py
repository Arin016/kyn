from __future__ import annotations

from pathlib import Path

import pytest

from kyn.interactions import InteractionConflict, InteractionStore
from kyn.store import Store


def test_interactions_are_durable_idempotent_and_single_decision(tmp_path: Path) -> None:
    store = Store(tmp_path / "state")
    interactions = InteractionStore(store)
    created = interactions.create_permission(
        run_id="run-1",
        bot_name="builder",
        actor="channel:telegram:phone",
        request_id="request-1",
        title="Run the test suite",
        tool_name="terminal.execute",
    )
    duplicate = interactions.create_permission(
        run_id="run-1",
        bot_name="builder",
        actor="channel:telegram:phone",
        request_id="request-1",
        title="Different display prose",
        tool_name="terminal.execute",
    )
    assert duplicate.id == created.id
    assert InteractionStore(store).require(created.id).status == "pending"

    resolved = interactions.resolve(created.id, "once", actor="telegram:111")
    assert resolved.status == "resolved"
    assert resolved.decided_by == "telegram:111"
    assert interactions.resolve(created.id, "once", actor="again").id == created.id
    with pytest.raises(InteractionConflict):
        interactions.resolve(created.id, "reject", actor="again")


def test_ask_queue_lines_up_oldest_first(tmp_path: Path) -> None:
    interactions = InteractionStore(Store(tmp_path / "state"))
    first = interactions.create_permission(
        run_id="run-1", bot_name="scout", actor="api", request_id="1",
        title="One", tool_name="one",
    )
    second = interactions.create_permission(
        run_id="run-2", bot_name="concierge", actor="api", request_id="2",
        title="Two", tool_name="two",
    )
    third = interactions.create_permission(
        run_id="run-3", bot_name="scout", actor="api", request_id="3",
        title="Three", tool_name="three",
    )
    assert [item.id for item in interactions.ask_queue()] == [first.id, second.id, third.id]

    interactions.resolve(first.id, "once", actor="tester")
    assert [item.id for item in interactions.ask_queue()] == [second.id, third.id]

    interactions.expire_run("run-2")
    assert [item.id for item in interactions.ask_queue()] == [third.id]


def test_expiring_a_run_closes_only_its_pending_interactions(tmp_path: Path) -> None:
    interactions = InteractionStore(Store(tmp_path / "state"))
    first = interactions.create_permission(
        run_id="run-1", bot_name="builder", actor="api", request_id="1",
        title="One", tool_name="one",
    )
    second = interactions.create_permission(
        run_id="run-2", bot_name="builder", actor="api", request_id="2",
        title="Two", tool_name="two",
    )
    assert interactions.expire_run("run-1") == 1
    assert interactions.require(first.id).status == "expired"
    assert interactions.require(second.id).status == "pending"
