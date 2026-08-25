from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pytest

from kiro_bot.delegation import (
    DelegationCoordinator,
    DelegationStore,
    EdgeSpec,
    InvalidGraph,
    NodeSpec,
)
from kiro_bot.store import Bot, Store


UTC = timezone.utc


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


def _service(tmp_path) -> tuple[DelegationStore, Clock]:
    store = Store(tmp_path)
    for name in ("researcher", "builder", "reviewer", "writer"):
        store.put_bot(Bot(name=name, cwd=str(tmp_path)))
    return DelegationStore(store), Clock()


def _diamond() -> tuple[list[NodeSpec], list[EdgeSpec]]:
    return (
        [
            NodeSpec("research", "researcher", "research", {"role": "input"}),
            NodeSpec("build", "builder", "build"),
            NodeSpec("review", "reviewer", "review"),
            NodeSpec("final", "writer", "final"),
        ],
        [
            EdgeSpec("research", "build"),
            EdgeSpec("research", "review"),
            EdgeSpec("build", "final"),
            EdgeSpec("review", "final"),
        ],
    )


def test_graph_persists_with_depths_edges_and_metadata(tmp_path) -> None:
    service, clock = _service(tmp_path)
    nodes, edges = _diamond()
    plan = service.create_plan(
        name="ship feature", nodes=nodes, edges=edges, now=clock()
    )

    reopened = DelegationStore(service.store)
    saved = reopened.get_plan(plan.id)
    assert saved is not None and saved.status == "pending"
    assert [(node.id, node.depth) for node in reopened.nodes(plan.id)] == [
        ("research", 0),
        ("build", 1),
        ("review", 1),
        ("final", 2),
    ]
    assert reopened.nodes(plan.id)[0].metadata == {"role": "input"}
    assert [(edge.source, edge.target) for edge in reopened.edges(plan.id)] == [
        ("build", "final"),
        ("research", "build"),
        ("research", "review"),
        ("review", "final"),
    ]


def test_graph_validation_rejects_cycles_fanout_depth_and_unknown_bots(tmp_path) -> None:
    service, clock = _service(tmp_path)
    with pytest.raises(InvalidGraph, match="cycle"):
        service.create_plan(
            name="cycle",
            nodes=[NodeSpec("a", "builder", "a"), NodeSpec("b", "reviewer", "b")],
            edges=[EdgeSpec("a", "b"), EdgeSpec("b", "a")],
            now=clock(),
        )
    with pytest.raises(InvalidGraph, match="fanout"):
        service.create_plan(
            name="wide",
            nodes=[
                NodeSpec("a", "builder", "a"),
                NodeSpec("b", "reviewer", "b"),
                NodeSpec("c", "writer", "c"),
            ],
            edges=[EdgeSpec("a", "b"), EdgeSpec("a", "c")],
            max_fanout=1,
            now=clock(),
        )
    with pytest.raises(InvalidGraph, match="depth"):
        service.create_plan(
            name="deep",
            nodes=[
                NodeSpec("a", "builder", "a"),
                NodeSpec("b", "reviewer", "b"),
                NodeSpec("c", "writer", "c"),
            ],
            edges=[EdgeSpec("a", "b"), EdgeSpec("b", "c")],
            max_depth=1,
            now=clock(),
        )
    with pytest.raises(InvalidGraph, match="does not exist"):
        service.create_plan(
            name="unknown",
            nodes=[NodeSpec("a", "missing", "a")],
            now=clock(),
        )


def test_ready_claims_are_atomic_across_coordinators(tmp_path) -> None:
    async def scenario() -> None:
        service, clock = _service(tmp_path)
        plan = service.create_plan(
            name="roots",
            nodes=[
                NodeSpec("a", "builder", "a"),
                NodeSpec("b", "reviewer", "b"),
            ],
            now=clock(),
        )
        first, second = await asyncio.gather(
            asyncio.to_thread(
                service.claim_ready,
                "one",
                plan_id=plan.id,
                limit=10,
                now=clock(),
            ),
            asyncio.to_thread(
                service.claim_ready,
                "two",
                plan_id=plan.id,
                limit=10,
                now=clock(),
            ),
        )
        ids = [node.id for node in first + second]
        assert sorted(ids) == ["a", "b"]
        assert len(ids) == len(set(ids))

    asyncio.run(scenario())


def test_coordinator_executes_dependencies_and_bounds_parallel_fanout(tmp_path) -> None:
    async def scenario() -> None:
        service, clock = _service(tmp_path)
        nodes, edges = _diamond()
        plan = service.create_plan(
            name="diamond", nodes=nodes, edges=edges, now=clock()
        )
        submit_order: list[str] = []
        active = 0
        max_active = 0
        run_to_prompt: dict[str, str] = {}

        async def submit(_bot: str, prompt: str) -> str:
            nonlocal active, max_active
            submit_order.append(prompt)
            run_id = f"run-{prompt}"
            run_to_prompt[run_id] = prompt
            active += 1
            max_active = max(max_active, active)
            return run_id

        async def wait(run_id: str) -> dict:
            nonlocal active
            await asyncio.sleep(0.005)
            active -= 1
            return {"id": run_id, "status": "complete", "answer": run_to_prompt[run_id]}

        coordinator = DelegationCoordinator(
            service,
            submit,
            wait,
            max_concurrency=2,
            owner="coordinator",
            clock=clock,
        )
        completed = await coordinator.run_until_terminal(plan.id)

        assert completed.status == "succeeded"
        assert submit_order[0] == "research"
        assert set(submit_order[1:3]) == {"build", "review"}
        assert submit_order[3] == "final"
        assert max_active == 2
        assert [node.status for node in service.nodes(plan.id)] == [
            "succeeded",
            "succeeded",
            "succeeded",
            "succeeded",
        ]

    asyncio.run(scenario())


def test_failure_blocks_descendants_but_independent_branch_finishes(tmp_path) -> None:
    async def scenario() -> None:
        service, clock = _service(tmp_path)
        plan = service.create_plan(
            name="partial failure",
            nodes=[
                NodeSpec("bad", "builder", "fail"),
                NodeSpec("child", "writer", "must not run"),
                NodeSpec("independent", "reviewer", "independent"),
            ],
            edges=[EdgeSpec("bad", "child")],
            now=clock(),
        )
        submitted: list[str] = []

        async def submit(_bot: str, prompt: str) -> str:
            submitted.append(prompt)
            return f"run-{prompt}"

        async def wait(run_id: str) -> dict:
            if run_id == "run-fail":
                return {"status": "failed", "error": "boom"}
            return {"status": "complete", "value": 1}

        coordinator = DelegationCoordinator(service, submit, wait, clock=clock)
        completed = await coordinator.run_until_terminal(plan.id)
        states = {node.id: node for node in service.nodes(plan.id)}

        assert completed.status == "failed"
        assert states["bad"].status == "failed"
        assert states["child"].status == "blocked"
        assert states["independent"].status == "succeeded"
        assert "must not run" not in submitted

    asyncio.run(scenario())


def test_cancellation_marks_graph_and_forwards_running_run_ids(tmp_path) -> None:
    async def scenario() -> None:
        service, clock = _service(tmp_path)
        plan = service.create_plan(
            name="cancel",
            nodes=[NodeSpec("a", "builder", "a"), NodeSpec("b", "writer", "b")],
            edges=[EdgeSpec("a", "b")],
            now=clock(),
        )
        claimed = service.claim_ready("owner", plan_id=plan.id, now=clock())
        assert service.mark_running(plan.id, "a", "owner", "run-a", now=clock())
        cancelled: list[str] = []

        async def submit(_bot: str, _prompt: str) -> str:
            raise AssertionError("not used")

        async def wait(_run_id: str) -> dict:
            raise AssertionError("not used")

        async def cancel(run_id: str) -> None:
            cancelled.append(run_id)

        coordinator = DelegationCoordinator(
            service, submit, wait, cancel=cancel, clock=clock
        )
        saved = await coordinator.cancel_plan(plan.id)

        assert claimed[0].id == "a"
        assert saved.status == "cancelled"
        assert cancelled == ["run-a"]
        assert [node.status for node in service.nodes(plan.id)] == [
            "cancelled",
            "cancelled",
        ]

    asyncio.run(scenario())


def test_aggregation_is_deterministic_and_contains_results(tmp_path) -> None:
    async def scenario() -> None:
        service, clock = _service(tmp_path)
        plan = service.create_plan(
            name="aggregate",
            nodes=[
                NodeSpec("z", "builder", "z", {"b": 2, "a": 1}),
                NodeSpec("a", "reviewer", "a"),
            ],
            now=clock(),
        )

        async def submit(_bot: str, prompt: str) -> str:
            return f"run-{prompt}"

        async def wait(run_id: str) -> dict:
            return {"status": "complete", "run": run_id, "nested": {"z": 1, "a": 2}}

        coordinator = DelegationCoordinator(service, submit, wait, clock=clock)
        await coordinator.run_until_terminal(plan.id)
        first = service.aggregation(plan.id)
        second = DelegationStore(service.store).aggregation(plan.id)

        assert first == second
        assert [item["node_id"] for item in first["nodes"]] == ["z", "a"]
        assert first["counts"]["succeeded"] == 2
        assert first["nodes"][0]["result"]["status"] == "complete"

    asyncio.run(scenario())


def test_paused_plan_is_not_claimable_until_explicit_start(tmp_path) -> None:
    service, clock = _service(tmp_path)
    plan = service.create_plan(
        name="draft",
        nodes=[NodeSpec("a", "builder", "a")],
        start=False,
        now=clock(),
    )
    assert plan.status == "paused"
    assert service.list_plans(status="paused") == [plan]
    assert service.claim_ready("worker", plan_id=plan.id, now=clock()) == []

    started = service.start_plan(plan.id, now=clock())
    assert started.status == "pending"
    assert [node.id for node in service.claim_ready("worker", plan_id=plan.id, now=clock())] == ["a"]


def test_long_plan_does_not_starve_an_independent_plan(tmp_path) -> None:
    async def scenario() -> None:
        service, clock = _service(tmp_path)
        slow = service.create_plan(
            name="slow",
            nodes=[NodeSpec("slow", "builder", "slow")],
            now=clock(),
        )
        fast = service.create_plan(
            name="fast",
            nodes=[NodeSpec("fast", "reviewer", "fast")],
            now=clock(),
        )
        slow_started = asyncio.Event()
        release_slow = asyncio.Event()

        async def submit(_bot: str, prompt: str) -> str:
            return f"run-{prompt}"

        async def wait(run_id: str) -> dict:
            if run_id == "run-slow":
                slow_started.set()
                await release_slow.wait()
            return {"status": "complete", "id": run_id}

        coordinator = DelegationCoordinator(
            service, submit, wait, max_concurrency=2, clock=clock
        )
        slow_tick = asyncio.create_task(coordinator.tick(slow.id))
        await slow_started.wait()
        assert await asyncio.wait_for(coordinator.tick(fast.id), timeout=0.2) == 1
        assert service.get_plan(fast.id).status == "succeeded"  # type: ignore[union-attr]
        release_slow.set()
        await slow_tick

    asyncio.run(scenario())


def test_cancelled_tick_releases_running_node_for_immediate_recovery(tmp_path) -> None:
    async def scenario() -> None:
        service, clock = _service(tmp_path)
        plan = service.create_plan(
            name="recover",
            nodes=[NodeSpec("a", "builder", "a")],
            now=clock(),
        )
        waiting = asyncio.Event()

        async def submit(_bot: str, _prompt: str) -> str:
            return "run-a"

        async def wait(_run_id: str) -> dict:
            waiting.set()
            await asyncio.Event().wait()
            return {"status": "complete"}

        coordinator = DelegationCoordinator(service, submit, wait, clock=clock)
        tick = asyncio.create_task(coordinator.tick(plan.id))
        await waiting.wait()
        tick.cancel()
        await asyncio.gather(tick, return_exceptions=True)

        recovered = service.claim_ready("replacement", plan_id=plan.id, now=clock())
        assert len(recovered) == 1
        assert recovered[0].status == "running"
        assert recovered[0].run_id == "run-a"

    asyncio.run(scenario())
