from __future__ import annotations

import asyncio
import subprocess
import threading
from collections import defaultdict
from pathlib import Path
from typing import AsyncIterator

import pytest

from kiro_bot.engine import Engine
from kiro_bot.governance import GovernanceStore, Policy, QuotaExceeded
from kiro_bot.memory import SharedMemoryStore
from kiro_bot.protocol import Event
from kiro_bot.plugins import PluginRegistry
from kiro_bot.run_store import RunRepository
from kiro_bot.store import Bot, Store
from kiro_bot.workspaces import WorkspaceExecutionSpec, WorkspaceManager


async def _wait_for_status(engine: Engine, run_id: str, status: str) -> dict:
    for _ in range(200):
        snapshot = await engine.get_run(run_id)
        if snapshot["status"] == status:
            return snapshot
        await asyncio.sleep(0.005)
    raise AssertionError(f"run {run_id} did not reach {status}")


class FakeSession:
    def __init__(self) -> None:
        self.decisions: list[tuple[str, str | int, bool]] = []
        self.cancelled = asyncio.Event()
        self.permission_decided = asyncio.Event()

    async def approve(self, request_id: str | int, *, always: bool = False) -> None:
        self.decisions.append(("approve", request_id, always))
        self.permission_decided.set()

    async def reject(self, request_id: str | int) -> None:
        self.decisions.append(("reject", request_id, False))
        self.permission_decided.set()

    async def cancel(self) -> None:
        self.cancelled.set()


class FakeOrchestrator:
    def __init__(self, hub: "FakeHub") -> None:
        self.hub = hub
        self.bot_name = ""
        self.session = FakeSession()
        self.closed = False
        self.cwd: str | None = None

    async def open(self, bot_name: str, *, cwd: str | None = None) -> FakeSession:
        self.bot_name = bot_name
        self.cwd = cwd
        self.hub.instances[bot_name] = self
        self.hub.opens.append((bot_name, cwd))
        return self.session

    async def run(self, message: str) -> AsyncIterator[Event]:
        self.hub.starts.append((self.bot_name, message))
        self.hub.active += 1
        self.hub.max_active = max(self.hub.max_active, self.hub.active)
        self.hub.started[(self.bot_name, message)].set()
        try:
            gate = self.hub.gates.get((self.bot_name, message))
            if gate is not None:
                await gate.wait()
            if message == "permission":
                yield Event(
                    kind="permission",
                    request_id="request-1",
                    tool_call_id="tool-1",
                    title="Write file",
                    options=[{"optionId": "allow_once"}],
                )
                await self.session.permission_decided.wait()
            if message in {"policy-allow", "policy-deny"}:
                yield Event(
                    kind="permission",
                    request_id="request-policy",
                    tool_call_id="tool-policy",
                    tool_name="filesystem.write",
                    title="Untrusted display title",
                    options=[{"optionId": "allow_once"}, {"optionId": "reject"}],
                )
                await self.session.permission_decided.wait()
            if message == "plugin-missing":
                yield Event(
                    kind="permission",
                    request_id="request-plugin",
                    tool_call_id="tool-plugin",
                    tool_name="filesystem.write",
                    mcp_server_name="deleted-plugin",
                    title="Looks safe",
                    options=[{"optionId": "allow_once"}, {"optionId": "reject"}],
                )
                await self.session.permission_decided.wait()
            if message == "hold":
                await asyncio.Event().wait()
            if message == "fail":
                raise RuntimeError("simulated turn failure")
            if message == "workspace-write":
                assert self.cwd is not None
                Path(self.cwd, "artifact.txt").write_text(
                    "workspace result\n", encoding="utf-8"
                )
            yield Event(kind="text", text=f"{self.bot_name}:{message}")
            yield Event(kind="complete", stop_reason="end_turn")
        finally:
            self.hub.active -= 1

    async def close(self) -> None:
        self.closed = True


class FakeHub:
    def __init__(self) -> None:
        self.instances: dict[str, FakeOrchestrator] = {}
        self.starts: list[tuple[str, str]] = []
        self.started: defaultdict[tuple[str, str], asyncio.Event] = defaultdict(asyncio.Event)
        self.gates: dict[tuple[str, str], asyncio.Event] = {}
        self.active = 0
        self.max_active = 0
        self.opens: list[tuple[str, str | None]] = []

    def factory(self, _bot_name: str) -> FakeOrchestrator:
        return FakeOrchestrator(self)


def test_same_bot_is_fifo_and_reuses_one_orchestrator() -> None:
    async def scenario() -> None:
        hub = FakeHub()
        first_gate = asyncio.Event()
        hub.gates[("alpha", "first")] = first_gate
        engine = Engine(orchestrator_factory=hub.factory)
        await engine.start()
        try:
            first = await engine.submit("alpha", "first")
            second = await engine.submit("alpha", "second")
            await hub.started[("alpha", "first")].wait()
            await asyncio.sleep(0.02)
            assert hub.starts == [("alpha", "first")]
            assert (await engine.get_run(second))["status"] == "queued"

            first_gate.set()
            await _wait_for_status(engine, first, "complete")
            await _wait_for_status(engine, second, "complete")
            assert hub.starts == [("alpha", "first"), ("alpha", "second")]
            assert list(hub.instances) == ["alpha"]
        finally:
            await engine.close()

    asyncio.run(scenario())


def test_different_bots_run_concurrently() -> None:
    async def scenario() -> None:
        hub = FakeHub()
        alpha_gate = asyncio.Event()
        beta_gate = asyncio.Event()
        hub.gates[("alpha", "work")] = alpha_gate
        hub.gates[("beta", "work")] = beta_gate
        engine = Engine(orchestrator_factory=hub.factory)
        await engine.start()
        try:
            alpha = await engine.submit("alpha", "work")
            beta = await engine.submit("beta", "work")
            await asyncio.gather(
                hub.started[("alpha", "work")].wait(),
                hub.started[("beta", "work")].wait(),
            )
            assert hub.max_active == 2
            alpha_gate.set()
            beta_gate.set()
            await _wait_for_status(engine, alpha, "complete")
            await _wait_for_status(engine, beta, "complete")
        finally:
            await engine.close()

    asyncio.run(scenario())


def test_local_run_receives_cross_surface_memory_without_mutating_public_message(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        store = Store(tmp_path / "store")
        store.put_bot(Bot("alpha", str(tmp_path)))
        memory = SharedMemoryStore(store)
        memory.record(
            "alpha",
            "channel:whatsapp:personal:thread",
            "channel:whatsapp:personal",
            "We chose SQLite for the local index",
            "Decision recorded.",
            event_id="channel-event",
        )
        hub = FakeHub()
        engine = Engine(
            store=store,
            memory=memory,
            orchestrator_factory=hub.factory,
            recover_on_start=False,
        )
        await engine.start()
        try:
            run_id = await engine.submit("alpha", "Continue the local index work")
            snapshot = await _wait_for_status(engine, run_id, "complete")
            assert snapshot["message"] == "Continue the local index work"
            executed = hub.starts[0][1]
            assert "We chose SQLite" in executed
            assert executed.endswith("Current request:\nContinue the local index work")
            local = memory.list_events("alpha", scope="local")
            assert len(local) == 1
            assert local[0].request_text == "Continue the local index work"
        finally:
            await engine.close()

    asyncio.run(scenario())


def test_external_channel_turns_use_fresh_isolated_sessions(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = Store(tmp_path / "state")
        store.put_bot(Bot("alpha", str(tmp_path)))
        hub = FakeHub()
        engine = Engine(store=store, orchestrator_factory=hub.factory)
        await engine.start()
        try:
            first = await engine.submit(
                "alpha", "first remote thread", actor="channel:slack:engineering"
            )
            await _wait_for_status(engine, first, "complete")
            second = await engine.submit(
                "alpha", "second remote thread", actor="channel:github:repository"
            )
            await _wait_for_status(engine, second, "complete")
            normal = await engine.submit("alpha", "normal persistent chat")
            await _wait_for_status(engine, normal, "complete")
        finally:
            await engine.close()

        assert hub.opens == [
            ("alpha", str(tmp_path)),
            ("alpha", str(tmp_path)),
            ("alpha", None),
        ]

    asyncio.run(scenario())


def test_subscription_delivers_ordered_history_and_live_events() -> None:
    async def scenario() -> None:
        hub = FakeHub()
        gate = asyncio.Event()
        hub.gates[("alpha", "stream")] = gate
        engine = Engine(orchestrator_factory=hub.factory)
        await engine.start()
        try:
            run_id = await engine.submit("alpha", "stream")
            subscription = engine.subscribe(run_id)
            collector = asyncio.create_task(_collect(subscription))
            await hub.started[("alpha", "stream")].wait()
            gate.set()
            events = await asyncio.wait_for(collector, timeout=1)
            assert [event["sequence"] for event in events] == [1, 2]
            assert [event["kind"] for event in events] == ["text", "complete"]
            assert events[0]["text"] == "alpha:stream"

            replay = [event async for event in engine.subscribe(run_id, after_sequence=1)]
            assert [event["sequence"] for event in replay] == [2]
            snapshot = await engine.get_run(run_id)
            assert snapshot["status"] == "complete"
            assert snapshot["stop_reason"] == "end_turn"
        finally:
            await engine.close()

    asyncio.run(scenario())


def test_permission_decision_resumes_only_the_waiting_run() -> None:
    async def scenario() -> None:
        hub = FakeHub()
        engine = Engine(orchestrator_factory=hub.factory)
        await engine.start()
        try:
            run_id = await engine.submit("alpha", "permission")
            snapshot = await _wait_for_status(engine, run_id, "waiting_permission")
            assert snapshot["events"][0]["request_id"] == "request-1"

            with pytest.raises(ValueError, match="once or reject"):
                await engine.decide_permission(run_id, "request-1", "always")  # type: ignore[arg-type]
            await engine.decide_permission(run_id, "request-1", "once")
            complete = await _wait_for_status(engine, run_id, "complete")
            assert complete["stop_reason"] == "end_turn"
            assert hub.instances["alpha"].session.decisions == [
                ("approve", "request-1", False)
            ]
        finally:
            await engine.close()

    asyncio.run(scenario())


def test_cancel_releases_worker_for_next_turn() -> None:
    async def scenario() -> None:
        hub = FakeHub()
        engine = Engine(orchestrator_factory=hub.factory)
        await engine.start()
        try:
            held = await engine.submit("alpha", "hold")
            following = await engine.submit("alpha", "after")
            await hub.started[("alpha", "hold")].wait()
            held_session = hub.instances["alpha"].session

            cancelled = await engine.cancel(held)
            assert cancelled["status"] == "cancelled"
            assert cancelled["finished_at"] is not None
            assert held_session.cancelled.is_set()
            complete = await _wait_for_status(engine, following, "complete")
            assert complete["events"][0]["text"] == "alpha:after"
        finally:
            await engine.close()

    asyncio.run(scenario())


def test_turn_failure_restarts_orchestrator_and_keeps_worker_alive() -> None:
    async def scenario() -> None:
        hub = FakeHub()
        engine = Engine(orchestrator_factory=hub.factory)
        await engine.start()
        try:
            failed_id = await engine.submit("alpha", "fail")
            next_id = await engine.submit("alpha", "recovered")
            failed = await _wait_for_status(engine, failed_id, "failed")
            recovered = await _wait_for_status(engine, next_id, "complete")
            assert "simulated turn failure" in failed["error"]
            assert recovered["events"][0]["text"] == "alpha:recovered"
            assert hub.starts == [("alpha", "fail"), ("alpha", "recovered")]
        finally:
            await engine.close()

    asyncio.run(scenario())


def test_governance_auto_decides_from_canonical_tool_and_audits(tmp_path) -> None:
    async def scenario() -> None:
        store = Store(tmp_path)
        store.put_bot(Bot(name="alpha", cwd=str(tmp_path)))
        governance = GovernanceStore(store)
        governance.set_policy(
            "alpha",
            Policy(
                approval_mode="allow_list",
                allowed_tools=("filesystem.write",),
            ),
        )
        hub = FakeHub()
        engine = Engine(
            store=store,
            governance=governance,
            orchestrator_factory=hub.factory,
        )
        await engine.start()
        try:
            run_id = await engine.submit("alpha", "policy-allow")
            await _wait_for_status(engine, run_id, "complete")
            assert hub.instances["alpha"].session.decisions == [
                ("approve", "request-policy", False)
            ]
            audit = list(reversed(governance.list_audit(run_id=run_id)))
            assert [item["event_type"] for item in audit] == [
                "run_submission",
                "permission_decision",
                "run_outcome",
            ]
            assert audit[1]["canonical_tool_name"] == "filesystem.write"
            assert audit[1]["outcome"] == "approve"
            assert all("prompt" not in item for item in audit)
        finally:
            await engine.close()

    asyncio.run(scenario())


def test_builtin_tool_without_mcp_server_uses_governance_not_plugin_registry(
    tmp_path,
) -> None:
    async def scenario() -> None:
        store = Store(tmp_path / "store")
        store.put_bot(Bot(name="alpha", cwd=str(tmp_path)))
        governance = GovernanceStore(store)
        governance.set_policy(
            "alpha",
            Policy(approval_mode="allow_list", allowed_tools=("filesystem.write",)),
        )
        plugins = PluginRegistry(store)
        hub = FakeHub()
        engine = Engine(
            store=store,
            governance=governance,
            plugins=plugins,
            orchestrator_factory=hub.factory,
        )
        await engine.start()
        try:
            run_id = await engine.submit("alpha", "policy-allow")
            snapshot = await _wait_for_status(engine, run_id, "complete")
            assert snapshot["status"] == "complete"
            assert hub.instances["alpha"].session.decisions == [
                ("approve", "request-policy", False)
            ]
        finally:
            await engine.close()

    asyncio.run(scenario())


def test_governance_quota_rejects_before_queueing(tmp_path) -> None:
    async def scenario() -> None:
        store = Store(tmp_path)
        store.put_bot(Bot(name="alpha", cwd=str(tmp_path)))
        governance = GovernanceStore(store)
        governance.set_policy("alpha", Policy(max_concurrent_runs=1))
        hub = FakeHub()
        engine = Engine(
            store=store,
            governance=governance,
            orchestrator_factory=hub.factory,
        )
        await engine.start()
        try:
            first = await engine.submit("alpha", "hold")
            await hub.started[("alpha", "hold")].wait()
            with pytest.raises(QuotaExceeded, match="concurrent"):
                await engine.submit("alpha", "never-queued")
            assert hub.starts == [("alpha", "hold")]
            await engine.cancel(first)
        finally:
            await engine.close()

    asyncio.run(scenario())


def test_missing_plugin_is_denied_fail_closed(tmp_path) -> None:
    async def scenario() -> None:
        store = Store(tmp_path)
        store.put_bot(Bot(name="alpha", cwd=str(tmp_path)))
        governance = GovernanceStore(store)
        plugins = PluginRegistry(store)
        hub = FakeHub()
        engine = Engine(
            store=store,
            governance=governance,
            plugins=plugins,
            orchestrator_factory=hub.factory,
        )
        await engine.start()
        try:
            run_id = await engine.submit("alpha", "plugin-missing")
            await _wait_for_status(engine, run_id, "complete")
            assert hub.instances["alpha"].session.decisions == [
                ("reject", "request-plugin", False)
            ]
            audit = governance.list_audit(run_id=run_id)
            permission = next(row for row in audit if row["event_type"] == "permission_decision")
            assert permission["reason"] == "plugin_not_registered"
            assert permission["outcome"] == "deny"
        finally:
            await engine.close()

    asyncio.run(scenario())


def test_engine_recovers_an_interrupted_durable_run_on_startup(tmp_path) -> None:
    async def scenario() -> None:
        store = Store(tmp_path)
        store.put_bot(Bot(name="alpha", cwd=str(tmp_path)))
        governance = GovernanceStore(store)
        repository = RunRepository(store)
        repository.enqueue("recovered-run", "alpha", "recovered", actor="scheduler")
        old = repository.claim("recovered-run", "dead-daemon", lease_seconds=3600)
        assert old is not None
        governance.reserve_run("alpha", "recovered-run", actor="scheduler")

        hub = FakeHub()
        engine = Engine(
            store=store,
            governance=governance,
            run_repository=repository,
            orchestrator_factory=hub.factory,
        )
        await engine.start()
        try:
            complete = await _wait_for_status(engine, "recovered-run", "complete")
            assert complete["actor"] == "scheduler"
            assert complete["events"][0]["text"] == "alpha:recovered"
            assert repository.get("recovered-run").status == "complete"
            assert hub.starts == [("alpha", "recovered")]
        finally:
            await engine.close()

    asyncio.run(scenario())


def test_only_one_controller_can_own_a_store(tmp_path) -> None:
    async def scenario() -> None:
        store = Store(tmp_path)
        first = Engine(store=store, orchestrator_factory=FakeHub().factory)
        second = Engine(store=store, orchestrator_factory=FakeHub().factory)
        await first.start()
        try:
            with pytest.raises(RuntimeError, match="already active"):
                await second.start()
        finally:
            await first.close()

        replacement = Engine(store=store, orchestrator_factory=FakeHub().factory)
        await replacement.start()
        await replacement.close()

    asyncio.run(scenario())


def test_terminal_snapshot_and_subscription_survive_restart(tmp_path) -> None:
    async def scenario() -> None:
        store = Store(tmp_path)
        store.put_bot(Bot(name="alpha", cwd=str(tmp_path)))
        repository = RunRepository(store)
        repository.enqueue("done", "alpha", "finished")
        lease = repository.claim("done", "old-engine")
        assert lease is not None
        repository.finish("done", lease.token, "complete")

        engine = Engine(
            store=store,
            run_repository=repository,
            orchestrator_factory=FakeHub().factory,
        )
        await engine.start()
        try:
            snapshot = await engine.get_run("done")
            assert snapshot["status"] == "complete"
            assert snapshot["events"] == []
            assert [event async for event in engine.subscribe("done")] == []
        finally:
            await engine.close()

    asyncio.run(scenario())


def test_startup_restores_every_queued_page(tmp_path) -> None:
    async def scenario() -> None:
        store = Store(tmp_path)
        store.put_bot(Bot(name="alpha", cwd=str(tmp_path)))
        repository = RunRepository(store, max_terminal_runs=2_000)
        for index in range(1_001):
            repository.enqueue(f"run-{index:04}", "alpha", f"message-{index}")
        hub = FakeHub()
        hub.gates[("alpha", "message-0")] = asyncio.Event()
        engine = Engine(
            run_repository=repository,
            orchestrator_factory=hub.factory,
            max_runs=2_000,
        )
        await engine.start()
        try:
            assert len(engine._runs) == 1_001
            assert "run-1000" in engine._runs
        finally:
            await engine.close()

    asyncio.run(scenario())


def test_claim_failure_does_not_kill_bot_worker(tmp_path) -> None:
    class FailFirstClaimRepository(RunRepository):
        def __init__(self, store: Store) -> None:
            super().__init__(store)
            self.failed = False

        def claim(self, run_id, worker_id, **kwargs):
            if not self.failed:
                self.failed = True
                return None
            return super().claim(run_id, worker_id, **kwargs)

    async def scenario() -> None:
        store = Store(tmp_path)
        store.put_bot(Bot(name="alpha", cwd=str(tmp_path)))
        repository = FailFirstClaimRepository(store)
        hub = FakeHub()
        engine = Engine(run_repository=repository, orchestrator_factory=hub.factory)
        await engine.start()
        try:
            failed = await engine.submit("alpha", "first")
            following = await engine.submit("alpha", "second")
            assert (await _wait_for_status(engine, failed, "failed"))["status"] == "failed"
            assert (await _wait_for_status(engine, following, "complete"))["status"] == "complete"
        finally:
            await engine.close()

    asyncio.run(scenario())


def test_cancel_serializes_with_durable_claim(tmp_path) -> None:
    class BlockingClaimRepository(RunRepository):
        def __init__(self, store: Store) -> None:
            super().__init__(store)
            self.claim_started = threading.Event()
            self.release_claim = threading.Event()

        def claim(self, *args, **kwargs):
            self.claim_started.set()
            self.release_claim.wait(timeout=2)
            return super().claim(*args, **kwargs)

    async def scenario() -> None:
        store = Store(tmp_path)
        store.put_bot(Bot(name="alpha", cwd=str(tmp_path)))
        repository = BlockingClaimRepository(store)
        engine = Engine(run_repository=repository, orchestrator_factory=FakeHub().factory)
        await engine.start()
        try:
            run_id = await engine.submit("alpha", "hold")
            assert await asyncio.to_thread(repository.claim_started.wait, 1)
            cancelling = asyncio.create_task(engine.cancel(run_id))
            await asyncio.sleep(0.01)
            repository.release_claim.set()
            result = await asyncio.wait_for(cancelling, timeout=2)
            assert result["status"] == "cancelled"
            assert repository.get(run_id).status == "cancelled"
        finally:
            repository.release_claim.set()
            await engine.close()

    asyncio.run(scenario())


def test_durable_lease_is_renewed_while_turn_is_running(tmp_path, monkeypatch) -> None:
    import kiro_bot.engine as engine_module

    class WatchingRepository(RunRepository):
        def __init__(self, store: Store) -> None:
            super().__init__(store)
            self.renewed = threading.Event()

        def renew_lease(self, *args, **kwargs):
            lease = super().renew_lease(*args, **kwargs)
            self.renewed.set()
            return lease

    async def scenario() -> None:
        monkeypatch.setattr(engine_module, "_DURABLE_HEARTBEAT_SECONDS", 0.01)
        store = Store(tmp_path)
        store.put_bot(Bot(name="alpha", cwd=str(tmp_path)))
        repository = WatchingRepository(store)
        hub = FakeHub()
        gate = asyncio.Event()
        hub.gates[("alpha", "long")] = gate
        engine = Engine(run_repository=repository, orchestrator_factory=hub.factory)
        await engine.start()
        try:
            run_id = await engine.submit("alpha", "long")
            await hub.started[("alpha", "long")].wait()
            assert await asyncio.to_thread(repository.renewed.wait, 1)
            gate.set()
            await _wait_for_status(engine, run_id, "complete")
        finally:
            gate.set()
            await engine.close()

    asyncio.run(scenario())


def test_workspace_execution_propagates_cwd_and_finalizes_artifacts(tmp_path) -> None:
    async def scenario() -> None:
        repo = _make_repo(tmp_path)
        store = Store(tmp_path / "store")
        store.put_bot(Bot(name="alpha", cwd=str(repo)))
        workspaces = WorkspaceManager(store, tmp_path / "worktrees")
        hub = FakeHub()
        engine = Engine(
            store=store,
            workspaces=workspaces,
            orchestrator_factory=hub.factory,
        )
        await engine.start()
        try:
            run_id = await engine.submit(
                "alpha",
                "workspace-write",
                execution=WorkspaceExecutionSpec(
                    repo_path=str(repo), artifact_paths=("artifact.txt",)
                ),
            )
            snapshot = await _wait_for_status(engine, run_id, "complete")
            workspace = snapshot["workspace"]
            assert workspace["state"] == "completed"
            assert workspace["artifacts"][0]["path"] == "artifact.txt"
            assert hub.opens[-1][1] == workspace["worktree_path"]

            legacy = await engine.submit("alpha", "legacy")
            legacy_snapshot = await _wait_for_status(engine, legacy, "complete")
            assert "workspace" not in legacy_snapshot
            assert hub.opens[-1] == ("alpha", None)
        finally:
            await engine.close()

    asyncio.run(scenario())


def test_supplied_workspace_can_span_turns_without_auto_finalization(tmp_path) -> None:
    async def scenario() -> None:
        repo = _make_repo(tmp_path)
        store = Store(tmp_path / "store")
        store.put_bot(Bot(name="alpha", cwd=str(repo)))
        workspaces = WorkspaceManager(store, tmp_path / "worktrees")
        shared = workspaces.create_workspace(repo, "HEAD", "repair-group")
        hub = FakeHub()
        engine = Engine(
            store=store,
            workspaces=workspaces,
            orchestrator_factory=hub.factory,
        )
        await engine.start()
        try:
            spec = WorkspaceExecutionSpec(lease=shared, auto_finalize=False)
            first = await engine.submit("alpha", "first-pass", execution=spec)
            second = await engine.submit("alpha", "review-pass", execution=spec)
            await _wait_for_status(engine, first, "complete")
            await _wait_for_status(engine, second, "complete")

            manifest = workspaces.get_manifest("repair-group")
            assert manifest is not None and manifest.state == "active"
            retained = await engine.get_workspace_lease(second)
            assert retained.token == shared.token
            assert [cwd for _, cwd in hub.opens] == [shared.path]
        finally:
            await engine.close()

    asyncio.run(scenario())


def test_shared_workspace_serializes_different_bot_workers(tmp_path) -> None:
    async def scenario() -> None:
        repo = _make_repo(tmp_path)
        store = Store(tmp_path / "store")
        store.put_bot(Bot(name="alpha", cwd=str(repo)))
        store.put_bot(Bot(name="beta", cwd=str(repo)))
        workspaces = WorkspaceManager(store, tmp_path / "worktrees")
        shared = workspaces.create_workspace(repo, "HEAD", "shared-group")
        hub = FakeHub()
        gate = asyncio.Event()
        hub.gates[("alpha", "first")] = gate
        engine = Engine(
            store=store,
            workspaces=workspaces,
            orchestrator_factory=hub.factory,
        )
        await engine.start()
        try:
            spec = WorkspaceExecutionSpec(lease=shared, auto_finalize=False)
            first = await engine.submit("alpha", "first", execution=spec)
            await hub.started[("alpha", "first")].wait()
            second = await engine.submit("beta", "second", execution=spec)
            await asyncio.sleep(0.02)
            assert ("beta", "second") not in hub.starts
            gate.set()
            await _wait_for_status(engine, first, "complete")
            await _wait_for_status(engine, second, "complete")
        finally:
            gate.set()
            await engine.close()

    asyncio.run(scenario())


def test_queued_workspace_run_fails_if_its_lease_expires(tmp_path) -> None:
    async def scenario() -> None:
        repo = _make_repo(tmp_path)
        store = Store(tmp_path / "store")
        store.put_bot(Bot(name="alpha", cwd=str(repo)))
        workspaces = WorkspaceManager(store, tmp_path / "worktrees")
        hub = FakeHub()
        gate = asyncio.Event()
        hub.gates[("alpha", "long")] = gate
        engine = Engine(
            store=store,
            workspaces=workspaces,
            orchestrator_factory=hub.factory,
        )
        await engine.start()
        try:
            expiring = workspaces.create_workspace(
                repo, "HEAD", "expiring-group", lease_seconds=0.1
            )
            blocking = await engine.submit("alpha", "long")
            await hub.started[("alpha", "long")].wait()
            isolated = await engine.submit(
                "alpha",
                "never-started",
                execution=WorkspaceExecutionSpec(
                    lease=expiring,
                    lease_seconds=0.1,
                    auto_finalize=False,
                ),
            )
            await asyncio.sleep(0.15)
            gate.set()
            await _wait_for_status(engine, blocking, "complete")
            failed = await _wait_for_status(engine, isolated, "failed")
            assert "expired" in failed["error"]
            assert ("alpha", "never-started") not in hub.starts
        finally:
            gate.set()
            await engine.close()

    asyncio.run(scenario())


async def _collect(source: AsyncIterator[dict]) -> list[dict]:
    return [item async for item in source]


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"], check=True
    )
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "base"], check=True
    )
    return repo
