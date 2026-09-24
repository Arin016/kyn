from __future__ import annotations

import asyncio
import time
from typing import Any, Mapping

import pytest

from kyn.groups import (
    DONE_MARKER,
    GroupCoordinator,
    GroupNotFound,
    GroupStore,
    parse_mentions,
)
from kyn.store import Bot, Store


@pytest.fixture()
def store(tmp_path) -> Store:
    return Store(tmp_path / "kyn")


def add_bots(store: Store, *names: str, cwd: str = "/tmp") -> None:
    for name in names:
        store.put_bot(Bot(name=name, cwd=cwd))


class ScriptedEngine:
    """Engine double with scripted per-bot replies."""

    def __init__(self, replies: Mapping[str, list[str]] | None = None) -> None:
        self.replies = {key: list(value) for key, value in (replies or {}).items()}
        self.prompts: list[tuple[str, str]] = []
        self.cancelled: list[str] = []
        self.runs: dict[str, dict[str, Any]] = {}

    async def submit(self, bot_name: str, message: str) -> str:
        self.prompts.append((bot_name, message))
        run_id = f"run-{len(self.runs) + 1}"
        queue = self.replies.setdefault(bot_name, [])
        text = queue.pop(0) if queue else f"{bot_name} reply"
        self.runs[run_id] = {
            "id": run_id,
            "status": "complete",
            "events": [{"kind": "text", "text": text}],
        }
        return run_id

    async def wait(self, run_id: str) -> Mapping[str, Any]:
        return self.runs[run_id]

    async def cancel(self, run_id: str) -> bool:
        self.cancelled.append(run_id)
        self.runs.setdefault(run_id, {})["status"] = "cancelled"
        return True


def make_coordinator(store: Store, engine: ScriptedEngine) -> GroupCoordinator:
    return GroupCoordinator(GroupStore(store), engine.submit, engine.wait, cancel=engine.cancel)


# ---- store ----------------------------------------------------------------


def test_store_creates_lists_and_deletes_groups(store: Store) -> None:
    service = GroupStore(store)
    group = service.create_group("Launch room", "Ship the changelog", ["scout", "writer"])

    assert group.status == "idle"
    assert group.members == ["scout", "writer"]
    assert service.get_group(group.id) == group
    assert [item.id for item in service.list_groups()] == [group.id]

    assert service.delete_group(group.id) is True
    assert service.get_group(group.id) is None
    with pytest.raises(GroupNotFound):
        service.require_group(group.id)


def test_store_rejects_bad_groups(store: Store) -> None:
    service = GroupStore(store)
    with pytest.raises(ValueError):
        service.create_group("", "aim", ["scout"])
    with pytest.raises(ValueError):
        service.create_group("Room", "aim", [])
    with pytest.raises(ValueError):
        service.create_group("Room", "aim", ["scout"], max_rounds=0)
    with pytest.raises(ValueError):
        service.create_group("Room", "aim", [f"bot-{index}" for index in range(13)])


def test_store_deduplicates_members_and_pages_messages(store: Store) -> None:
    service = GroupStore(store)
    group = service.create_group("Room", "aim", ["scout", "scout", " writer "])
    assert group.members == ["scout", "writer"]

    first = service.add_message(group.id, "You", "human", "kick off")
    service.add_message(group.id, "scout", "bot", "on it")
    tail = service.messages(group.id, after=first.id)
    assert [message.author for message in tail] == ["scout"]
    assert service.count_messages(group.id) == 2
    with pytest.raises(ValueError):
        service.add_message(group.id, "scout", "bot", "   ")


# ---- coordinator ----------------------------------------------------------


def test_round_robin_bots_hear_each_other(store: Store) -> None:
    add_bots(store, "scout", "writer")
    engine = ScriptedEngine({"scout": ["Found 3 blockers."], "writer": ["Drafting the notes."]})
    coordinator = make_coordinator(store, engine)
    group = coordinator.service.create_group("Room", "Summarize blockers", ["scout", "writer"], max_rounds=1)

    asyncio.run(_run_once(coordinator, group.id))

    messages = coordinator.service.messages(group.id)
    assert [message.author for message in messages] == ["scout", "writer"]
    assert coordinator.service.get_group(group.id).status == "idle"

    # The second speaker is prompted with the first speaker's reply.
    writer_prompt = engine.prompts[1][1]
    assert "scout: Found 3 blockers." in writer_prompt
    assert "Shared aim: Summarize blockers" in writer_prompt


def test_done_marker_stops_the_group(store: Store) -> None:
    add_bots(store, "scout", "writer", "reviewer")
    engine = ScriptedEngine(
        {"scout": ["Done already."], "writer": [f"All set.\n{DONE_MARKER}"], "reviewer": ["should not run"]}
    )
    coordinator = make_coordinator(store, engine)
    group = coordinator.service.create_group("Room", "aim", ["scout", "writer", "reviewer"], max_rounds=3)

    asyncio.run(_run_once(coordinator, group.id))

    messages = coordinator.service.messages(group.id)
    assert [message.author for message in messages] == ["scout", "writer", "kyn"]
    assert messages[-1].role == "system"
    assert "aim as met" in messages[-1].text
    assert coordinator.service.get_group(group.id).status == "done"
    assert [name for name, _ in engine.prompts] == ["scout", "writer"]


def test_reply_mode_defaults_and_validates(store: Store) -> None:
    service = GroupStore(store)
    group = service.create_group("Room", "aim", ["scout"])
    assert group.reply_mode == "sequential"

    updated = service.set_reply_mode(group.id, "parallel")
    assert updated.reply_mode == "parallel"
    assert service.get_group(group.id).reply_mode == "parallel"

    with pytest.raises(ValueError):
        service.set_reply_mode(group.id, "relay")
    with pytest.raises(ValueError):
        service.create_group("Room", "aim", ["scout"], reply_mode="relay")
    with pytest.raises(GroupNotFound):
        service.set_reply_mode("missing", "parallel")


def test_parallel_round_fans_out_from_one_snapshot(store: Store) -> None:
    add_bots(store, "scout", "writer")
    engine = ScriptedEngine({"scout": ["Scout found one blocker."], "writer": ["Writer drafted notes."]})
    coordinator = make_coordinator(store, engine)
    group = coordinator.service.create_group(
        "Room", "Summarize blockers", ["scout", "writer"], max_rounds=1, reply_mode="parallel"
    )

    asyncio.run(_run_once(coordinator, group.id))

    messages = coordinator.service.messages(group.id)
    assert [message.author for message in messages] == ["scout", "writer"]
    assert coordinator.service.get_group(group.id).status == "idle"

    # Both members shared one transcript snapshot: neither prompt carries
    # the other member's same-round reply.
    prompts = {name: text for name, text in engine.prompts}
    assert "Writer drafted notes." not in prompts["scout"]
    assert "Scout found one blocker." not in prompts["writer"]
    assert "at the same time" in prompts["scout"]


def test_parallel_done_marker_stops_the_group(store: Store) -> None:
    add_bots(store, "scout", "writer")
    engine = ScriptedEngine({"scout": ["All green."], "writer": [f"Ship it.\n{DONE_MARKER}"]})
    coordinator = make_coordinator(store, engine)
    group = coordinator.service.create_group(
        "Room", "aim", ["scout", "writer"], max_rounds=3, reply_mode="parallel"
    )

    asyncio.run(_run_once(coordinator, group.id))

    assert coordinator.service.get_group(group.id).status == "done"
    assert "aim as met" in coordinator.service.messages(group.id)[-1].text


def test_parallel_speaking_lists_everyone_and_stop_cancels_all(store: Store) -> None:
    add_bots(store, "scout", "writer")
    engine = ScriptedEngine()
    started = asyncio.Event()

    async def blocking_wait(run_id: str) -> Mapping[str, Any]:
        started.set()
        await asyncio.sleep(30)
        return {"status": "complete", "events": [{"kind": "text", "text": "late"}]}

    coordinator = GroupCoordinator(
        GroupStore(store), engine.submit, blocking_wait, cancel=engine.cancel
    )
    group = coordinator.service.create_group(
        "Room", "aim", ["scout", "writer"], max_rounds=1, reply_mode="parallel"
    )

    async def scenario() -> None:
        await coordinator.start(group.id)
        for _ in range(100):
            if len(coordinator.speaking(group.id).get("bots", [])) == 2:
                break
            await asyncio.sleep(0.02)
        presence = coordinator.speaking(group.id)
        assert [entry["bot"] for entry in presence["bots"]] == ["scout", "writer"]
        await coordinator.stop(group.id)

    asyncio.run(scenario())

    assert sorted(engine.cancelled) == ["run-1", "run-2"]
    assert coordinator.is_running(group.id) is False
    assert coordinator.service.get_group(group.id).status == "stopped"


def test_failed_member_becomes_a_system_note(store: Store) -> None:
    add_bots(store, "scout", "writer")

    class FailingEngine(ScriptedEngine):
        async def wait(self, run_id: str) -> Mapping[str, Any]:
            return {"status": "failed", "error": "engine exploded"}

    engine = FailingEngine()
    coordinator = make_coordinator(store, engine)
    group = coordinator.service.create_group("Room", "aim", ["scout", "writer"], max_rounds=1)

    asyncio.run(_run_once(coordinator, group.id))

    messages = coordinator.service.messages(group.id)
    assert [message.role for message in messages] == ["system", "system"]
    assert "engine exploded" in messages[0].text
    assert len(engine.prompts) == 2


def test_submit_failure_does_not_stall_the_group(store: Store) -> None:
    add_bots(store, "scout", "writer")

    class BrokenEngine(ScriptedEngine):
        async def submit(self, bot_name: str, message: str) -> str:
            if bot_name == "scout":
                raise RuntimeError("no session")
            return await super().submit(bot_name, message)

    engine = BrokenEngine({"writer": ["Carrying on."]})
    coordinator = make_coordinator(store, engine)
    group = coordinator.service.create_group("Room", "aim", ["scout", "writer"], max_rounds=1)

    asyncio.run(_run_once(coordinator, group.id))

    messages = coordinator.service.messages(group.id)
    assert "no session" in messages[0].text
    assert (messages[1].author, messages[1].role) == ("writer", "bot")


def test_human_message_is_in_the_next_prompt(store: Store) -> None:
    add_bots(store, "scout")
    engine = ScriptedEngine({"scout": ["Understood."]})
    coordinator = make_coordinator(store, engine)
    group = coordinator.service.create_group("Room", "aim", ["scout"], max_rounds=1)

    async def scenario() -> None:
        await coordinator.post_message(group.id, "focus on the parser", respond=False)
        await coordinator.start(group.id, rounds=1)
        await coordinator.wait(group.id)

    asyncio.run(scenario())

    prompt = engine.prompts[0][1]
    assert "operator: focus on the parser" in prompt
    assert coordinator.service.messages(group.id)[0].role == "human"


def test_stop_cancels_the_in_flight_run(store: Store) -> None:
    add_bots(store, "scout")
    engine = ScriptedEngine()
    started = asyncio.Event()

    async def blocking_wait(run_id: str) -> Mapping[str, Any]:
        started.set()
        await asyncio.sleep(30)
        return {"status": "complete", "events": [{"kind": "text", "text": "late"}]}

    coordinator = GroupCoordinator(
        GroupStore(store), engine.submit, blocking_wait, cancel=engine.cancel
    )
    group = coordinator.service.create_group("Room", "aim", ["scout"], max_rounds=2)

    async def scenario() -> None:
        await coordinator.start(group.id)
        await asyncio.wait_for(started.wait(), timeout=2)
        await coordinator.stop(group.id)

    asyncio.run(scenario())

    assert engine.cancelled == ["run-1"]
    assert coordinator.is_running(group.id) is False
    assert coordinator.service.get_group(group.id).status == "stopped"


def test_turn_budget_halts_a_long_group(store: Store) -> None:
    add_bots(store, "scout")
    engine = ScriptedEngine()
    coordinator = make_coordinator(store, engine)
    coordinator.turn_budget = 3
    group = coordinator.service.create_group("Room", "aim", ["scout"], max_rounds=5)

    asyncio.run(_run_once(coordinator, group.id))

    messages = coordinator.service.messages(group.id)
    assert messages[-1].role == "system"
    assert "Turn budget" in messages[-1].text
    assert len(engine.prompts) == 3


def test_starting_twice_reuses_the_running_group(store: Store) -> None:
    add_bots(store, "scout")
    engine = ScriptedEngine({"scout": ["first reply", "second reply"]})
    coordinator = make_coordinator(store, engine)
    group = coordinator.service.create_group("Room", "aim", ["scout"], max_rounds=1)

    async def scenario() -> None:
        await coordinator.start(group.id)
        await coordinator.start(group.id)
        await coordinator.wait(group.id)

    asyncio.run(scenario())

    assert len(engine.prompts) == 1


async def _run_once(coordinator: GroupCoordinator, group_id: str) -> None:
    await coordinator.start(group_id)
    await coordinator.wait(group_id)


async def _run_once_post(
    coordinator: GroupCoordinator, group_id: str, text: str
) -> None:
    await coordinator.post_message(group_id, text)
    await coordinator.wait(group_id)


# ---- HTTP surface ---------------------------------------------------------


def test_group_endpoints_drive_a_full_round(tmp_path) -> None:
    fastapi = pytest.importorskip("fastapi")
    pytest.importorskip("starlette")
    from fastapi.testclient import TestClient

    from kyn.server import create_app

    store = Store(tmp_path / "kyn")
    add_bots(store, "scout", "writer")

    class TextEngine(ScriptedEngine):
        async def start(self) -> None:  # pragma: no cover - lifecycle no-op
            return None

        async def close(self) -> None:  # pragma: no cover - lifecycle no-op
            return None

        async def get_run(self, run_id: str) -> Mapping[str, Any] | None:
            return self.runs.get(run_id)

        async def subscribe(self, run_id: str, after: int = 0) -> Any:
            for event in self.runs[run_id]["events"]:
                yield event
            self.runs[run_id]["status"] = "complete"

    engine = TextEngine({"scout": ["Blockers listed."], "writer": ["Notes drafted."]})
    app = create_app(store, engine)

    with TestClient(app) as client:
        created = client.post(
            "/api/groups",
            json={"name": "Launch", "aim": "Ship notes", "members": ["scout", "writer"], "max_rounds": 1},
        )
        assert created.status_code == 201
        group_id = created.json()["group"]["id"]

        payload = client.get(f"/api/groups/{group_id}").json()
        for _ in range(100):
            if payload["group"]["status"] != "running":
                break
            time.sleep(0.02)
            payload = client.get(f"/api/groups/{group_id}").json()
        assert payload["group"]["status"] == "idle"
        assert [message["author"] for message in payload["messages"]] == ["scout", "writer"]
        assert payload["speaking"] == {}
        assert [member["name"] for member in payload["members"]] == ["scout", "writer"]

        listed = client.get("/api/groups").json()
        assert listed[0]["message_count"] == 2

        replied = client.post(f"/api/groups/{group_id}/messages", json={"text": "tighten it"})
        assert replied.status_code == 201
        assert replied.json()["message"]["role"] == "human"

        assert client.post(f"/api/groups/{group_id}/stop").json()["group"]["status"] == "stopped"
        assert client.delete(f"/api/groups/{group_id}").json()["deleted"] is True
        assert client.get(f"/api/groups/{group_id}").status_code == 404


def test_group_mode_endpoint_switches_fan_out(tmp_path) -> None:
    fastapi = pytest.importorskip("fastapi")
    pytest.importorskip("starlette")
    from fastapi.testclient import TestClient

    from kyn.server import create_app

    store = Store(tmp_path / "kyn")
    add_bots(store, "scout", "writer")

    class TextEngine(ScriptedEngine):
        async def start(self) -> None:  # pragma: no cover - lifecycle no-op
            return None

        async def close(self) -> None:  # pragma: no cover - lifecycle no-op
            return None

        async def get_run(self, run_id: str) -> Mapping[str, Any] | None:
            return self.runs.get(run_id)

        async def subscribe(self, run_id: str, after: int = 0) -> Any:
            for event in self.runs[run_id]["events"]:
                yield event
            self.runs[run_id]["status"] = "complete"

    engine = TextEngine({"scout": ["Blockers listed."], "writer": ["Notes drafted."]})
    app = create_app(store, engine)

    with TestClient(app) as client:
        created = client.post(
            "/api/groups",
            json={"name": "Launch", "aim": "Ship notes", "members": ["scout", "writer"], "max_rounds": 1},
        )
        assert created.status_code == 201
        assert created.json()["group"]["reply_mode"] == "sequential"
        group_id = created.json()["group"]["id"]

        switched = client.put(f"/api/groups/{group_id}/mode", json={"mode": "parallel"})
        assert switched.status_code == 200
        assert switched.json()["group"]["reply_mode"] == "parallel"

        assert client.put(f"/api/groups/{group_id}/mode", json={"mode": "relay"}).status_code == 422
        assert client.put("/api/groups/missing/mode", json={"mode": "parallel"}).status_code == 404

        payload = client.get(f"/api/groups/{group_id}").json()
        for _ in range(100):
            if payload["group"]["status"] != "running":
                break
            time.sleep(0.02)
            payload = client.get(f"/api/groups/{group_id}").json()
        assert payload["group"]["status"] == "idle"
        assert [message["author"] for message in payload["messages"]] == ["scout", "writer"]


def test_group_endpoints_reject_unknown_bots(tmp_path) -> None:
    pytest.importorskip("fastapi")
    pytest.importorskip("starlette")
    from fastapi.testclient import TestClient

    from kyn.server import create_app

    class NoopEngine:
        async def start(self) -> None:
            return None

        async def close(self) -> None:
            return None

        async def submit(self, bot_name: str, message: str) -> str:  # pragma: no cover
            raise AssertionError("no run should be submitted")

        async def get_run(self, run_id: str) -> None:  # pragma: no cover
            return None

    store = Store(tmp_path / "kyn")
    app = create_app(store, NoopEngine())

    with TestClient(app) as client:
        response = client.post(
            "/api/groups",
            json={"name": "Launch", "aim": "Ship notes", "members": ["ghost"]},
        )
    assert response.status_code == 404


# ---- mention routing -------------------------------------------------------


def test_parse_mentions_is_whole_token_and_ordered() -> None:
    assert parse_mentions("@writer please look", ["scout", "writer"]) == ["writer"]
    assert parse_mentions("hey scout and @Writer", ["scout", "writer"]) == ["writer"]
    assert parse_mentions("contact @scout then @writer", ["scout", "writer"]) == ["scout", "writer"]
    assert parse_mentions("email me at scout@corp.com", ["scout"]) == []
    assert parse_mentions("no one here", ["scout"]) == []
    assert parse_mentions("@ghost", ["scout"]) == []


def test_mentioned_bot_replies_alone(store: Store) -> None:
    add_bots(store, "scout", "writer")
    engine = ScriptedEngine({"writer": ["Only writer here."]})
    coordinator = make_coordinator(store, engine)
    group = coordinator.service.create_group("Room", "Ship notes", ["scout", "writer"], max_rounds=1)

    asyncio.run(
        _run_once_post(coordinator, group.id, "@writer what changed in the diff")
    )

    messages = coordinator.service.messages(group.id)
    assert [message.author for message in messages] == ["You", "writer"]
    assert coordinator.service.get_group(group.id).status == "idle"
    # Only the mentioned bot was prompted.
    assert [name for name, _prompt in engine.prompts] == ["writer"]
    assert "what changed in the diff" in engine.prompts[0][1]
    assert "@-mentioned you" in engine.prompts[0][1]


def test_mention_inside_running_round_redirects_next_turn(store: Store) -> None:
    add_bots(store, "scout", "writer")
    engine = ScriptedEngine({"scout": ["Working."], "writer": ["Writer picked it up."]})
    coordinator = make_coordinator(store, engine)
    group = coordinator.service.create_group("Room", "Ship notes", ["scout", "writer"], max_rounds=1)

    async def scenario() -> None:
        task = asyncio.create_task(coordinator.start(group.id))
        await asyncio.sleep(0.02)
        await coordinator.post_message(group.id, "@writer take the second pass")
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())

    messages = coordinator.service.messages(group.id)
    authors = [message.author for message in messages]
    # scout's original round-one turn still lands, but the mention redirects
    # the very next turn to writer, who then ends the directed round.
    assert authors[-1] == "writer"
    assert "take the second pass" in messages[-2].text


def test_plain_message_after_mention_returns_to_round_robin(store: Store) -> None:
    add_bots(store, "scout", "writer")
    engine = ScriptedEngine({"scout": ["Scout again."], "writer": ["Writer here."]})
    coordinator = make_coordinator(store, engine)
    group = coordinator.service.create_group("Room", "Ship notes", ["scout", "writer"], max_rounds=2)

    asyncio.run(_run_once_post(coordinator, group.id, "@writer start us off"))
    asyncio.run(_run_once_post(coordinator, group.id, "carry on everyone"))

    authors = [message.author for message in coordinator.service.messages(group.id)]
    # Directed round: You → writer. Then a plain message starts a normal round:
    # the operator's line lands, and round-robin resumes at scout, writer.
    assert authors == ["You", "writer", "You", "scout", "writer"]


# ---- pinned handoff brief --------------------------------------------------


def test_context_note_pins_and_clears(store: Store) -> None:
    service = GroupStore(store)
    group = service.create_group("Room", "Ship notes", ["scout"])
    assert service.context_note(group.id) == ""

    service.set_context_note(group.id, "scout found 3 blockers; writer owns the changelog")
    assert service.context_note(group.id) == "scout found 3 blockers; writer owns the changelog"

    service.set_context_note(group.id, "   ")
    assert service.context_note(group.id) == ""
    with pytest.raises(ValueError):
        service.set_context_note(group.id, "x" * 4001)


def test_context_note_rides_every_prompt(store: Store) -> None:
    add_bots(store, "scout", "writer")
    engine = ScriptedEngine({"scout": ["Ack."]})
    coordinator = make_coordinator(store, engine)
    group = coordinator.service.create_group("Room", "Ship notes", ["scout"], max_rounds=1)
    coordinator.service.set_context_note(group.id, "Blocker list lives in NOTES.md")

    asyncio.run(_run_once(coordinator, group.id))

    prompt = engine.prompts[0][1]
    assert "<pinned_context>" in prompt
    assert "Blocker list lives in NOTES.md" in prompt


# ---- HTTP surface ----------------------------------------------------------


def test_group_context_endpoint_and_mention_field(tmp_path) -> None:
    fastapi = pytest.importorskip("fastapi")
    pytest.importorskip("starlette")
    if fastapi is None:  # pragma: no cover
        return
    from fastapi.testclient import TestClient

    from kyn.server import create_app

    class TextEngine(ScriptedEngine):
        async def start(self) -> None:
            return None

        async def close(self) -> None:
            return None

        async def get_run(self, run_id: str) -> Mapping[str, Any] | None:
            return self.runs.get(run_id)

    store = Store(tmp_path / "kyn")
    add_bots(store, "scout", "writer")
    engine = TextEngine({"writer": ["On it."]})
    app = create_app(store, engine)

    with TestClient(app) as client:
        created = client.post(
            "/api/groups",
            json={"name": "Room", "aim": "Ship notes", "members": ["scout", "writer"]},
        )
        group_id = created.json()["group"]["id"]

        pinned = client.put(
            f"/api/groups/{group_id}/context",
            json={"note": "scout already drafted the outline"},
        )
        assert pinned.status_code == 200
        assert pinned.json()["context_note"] == "scout already drafted the outline"

        posted = client.post(
            f"/api/groups/{group_id}/messages",
            json={"text": "please check the numbers", "mentions": ["writer"], "respond": False},
        )
        assert posted.status_code == 201

        started = client.post(f"/api/groups/{group_id}/start?rounds=1")
        assert started.status_code == 200
        for _ in range(100):
            payload = client.get(f"/api/groups/{group_id}").json()
            if payload["group"]["status"] != "running":
                break
            time.sleep(0.02)
        # The explicit mention list routes the reply to writer.
        assert [message["author"] for message in payload["messages"]][-1] == "writer"
        assert client.put(f"/api/groups/{group_id}/context", json={"note": ""}).status_code == 200


def test_group_endpoint_rejects_oversized_note(tmp_path) -> None:
    pytest.importorskip("fastapi")
    pytest.importorskip("starlette")
    from fastapi.testclient import TestClient

    from kyn.server import create_app

    class NoopEngine:
        async def start(self) -> None:
            return None

        async def close(self) -> None:
            return None

        async def submit(self, bot_name: str, message: str) -> str:  # pragma: no cover
            raise AssertionError("no run should be submitted")

        async def get_run(self, run_id: str) -> None:  # pragma: no cover
            return None

    store = Store(tmp_path / "kyn")
    add_bots(store, "scout")
    app = create_app(store, NoopEngine())

    with TestClient(app) as client:
        created = client.post(
            "/api/groups", json={"name": "Room", "aim": "aim", "members": ["scout"]}
        )
        group_id = created.json()["group"]["id"]
        response = client.put(f"/api/groups/{group_id}/context", json={"note": "x" * 4001})
    assert response.status_code == 422


def test_transcript_ranks_relevance_over_recency(store: Store) -> None:
    add_bots(store, "scout", "writer")
    engine = ScriptedEngine()
    coordinator = make_coordinator(store, engine)
    group = coordinator.service.create_group("Room", "Fix the parser module", ["scout", "writer"])
    service = coordinator.service

    async def scenario() -> None:
        # Old but highly relevant to the aim and the speaker.
        await coordinator.post_message(
            group.id, "scout, the parser module crashes on empty input", respond=False
        )
        # A pile of irrelevant chatter that must not crowd out the above.
        for index in range(12):
            await coordinator.post_message(
                group.id, f"lunch anecdote number {index} about sandwiches", respond=False
            )

    asyncio.run(scenario())
    prompt = coordinator._prompt(group, "scout", 1)
    assert "parser module crashes on empty input" in prompt
    assert "[#" in prompt  # stable message references
    # The recent window survives verbatim...
    assert "lunch anecdote number 11 about sandwiches" in prompt
    # ...while stale chatter is dropped to protect the budget.
    assert "lunch anecdote number 0 about sandwiches" not in prompt
    assert len(prompt) <= coordinator.transcript_chars + 2_000


def test_mentioned_member_gets_directed_context(store: Store) -> None:
    add_bots(store, "scout", "writer")
    engine = ScriptedEngine({"writer": ["On it."]})
    coordinator = make_coordinator(store, engine)
    group = coordinator.service.create_group("Room", "Ship notes", ["scout", "writer"])

    async def scenario() -> None:
        await coordinator.post_message(group.id, "@writer take the second pass")
        await coordinator.wait(group.id)

    asyncio.run(scenario())
    prompt = engine.prompts[0][1]
    assert "operator @-mentioned you" in prompt
