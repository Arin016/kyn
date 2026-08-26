from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Literal, Protocol

from .orchestrator import BotOrchestrator
from .plugins import PluginRegistry
from .protocol import Event
from .store import Store
from .run_store import RunLease as DurableRunLease, RunRepository
from .workspaces import (
    WorkspaceExecution,
    WorkspaceExecutionSpec,
    WorkspaceLease,
    WorkspaceManager,
)
from .memory import SharedMemoryStore, local_scope
from .harness_context import compose_execution_prompt
from .interactions import InteractionStore

try:
    from .governance import GovernanceStore, RunLease
except ImportError:  # pragma: no cover - permits embedding the minimal core
    GovernanceStore = Any  # type: ignore[misc,assignment]
    RunLease = Any  # type: ignore[misc,assignment]


RunStatus = Literal[
    "queued",
    "running",
    "waiting_permission",
    "complete",
    "failed",
    "cancelled",
]
PermissionDecision = Literal["once", "reject"]

_TERMINAL_STATUSES = frozenset({"complete", "failed", "cancelled"})
_WORKER_STOP = object()
_DURABLE_LEASE_SECONDS = 300
_DURABLE_HEARTBEAT_SECONDS = 60
_WORKSPACE_HEARTBEAT_SECONDS = 60
_logger = logging.getLogger(__name__)


class RunNotFound(KeyError):
    """Raised when a run is unknown or has aged out of the retention window."""


class InvalidRunOperation(RuntimeError):
    """Raised when an operation is not valid for the run's current state."""


class _Session(Protocol):
    async def approve(self, request_id: str | int, *, always: bool = False) -> None: ...

    async def reject(self, request_id: str | int) -> None: ...

    async def cancel(self) -> None: ...


class _Orchestrator(Protocol):
    session: _Session | None

    async def open(self, bot_name: str, *, cwd: str | None = None) -> _Session: ...

    def run(self, message: str) -> AsyncIterator[Event]: ...

    async def close(self) -> None: ...


OrchestratorFactory = Callable[[str], _Orchestrator]


@dataclass(slots=True)
class _WorkspaceGuard:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


@dataclass(slots=True)
class _RunState:
    id: str
    bot_name: str
    message: str
    max_events: int
    status: RunStatus = "queued"
    stop_reason: str = ""
    error: str = ""
    created_at: str = field(default_factory=lambda: _now())
    started_at: str | None = None
    finished_at: str | None = None
    next_sequence: int = 1
    events: deque[dict[str, Any]] = field(init=False)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    permission_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending_permissions: dict[str, tuple[str | int, str]] = field(default_factory=dict)
    governance_lease: RunLease | None = None
    durable_lease: DurableRunLease | None = None
    actor: str = "api"
    finishing: bool = False
    workspace_execution: WorkspaceExecution | None = None
    workspace_manifest: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        self.events = deque(maxlen=self.max_events)

    @property
    def terminal(self) -> bool:
        return self.status in _TERMINAL_STATUSES

    def snapshot(self) -> dict[str, Any]:
        snapshot = {
            "id": self.id,
            "bot_name": self.bot_name,
            "message": self.message,
            "actor": self.actor,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "events": [_copy_json(event) for event in self.events],
        }
        if self.workspace_execution is not None:
            snapshot["workspace"] = (
                _copy_json(self.workspace_manifest)
                if self.workspace_manifest is not None
                else self.workspace_execution.summary()
            )
        return snapshot


class BotWorker:
    """A durable, single-consumer queue backed by one bot orchestrator."""

    def __init__(
        self,
        engine: "Engine",
        bot_name: str,
        orchestrator_factory: OrchestratorFactory,
    ) -> None:
        self.engine = engine
        self.bot_name = bot_name
        self._orchestrator_factory = orchestrator_factory
        self.orchestrator: _Orchestrator | None = None
        self.queue: asyncio.Queue[_RunState | object] = asyncio.Queue()
        self._loop_task: asyncio.Task[None] | None = None
        self._active_run_id: str | None = None
        self._active_task: asyncio.Task[None] | None = None
        self._closed = False
        self._orchestrator_cwd: str | None = None

    def start(self) -> None:
        if self._loop_task is None:
            self._loop_task = asyncio.create_task(
                self._run_loop(), name=f"kyn-worker:{self.bot_name}"
            )

    async def submit(self, run: _RunState) -> None:
        if self._closed:
            raise RuntimeError(f"worker for {self.bot_name!r} is closed")
        await self.queue.put(run)

    async def decide_permission(
        self, run_id: str, request_id: str | int, decision: PermissionDecision
    ) -> None:
        if self._active_run_id != run_id or self.orchestrator is None:
            raise InvalidRunOperation("run is not the active turn for its bot")
        session = self.orchestrator.session
        if session is None:
            raise InvalidRunOperation("the bot has no active Kiro session")
        if decision == "reject":
            await session.reject(request_id)
        else:
            await session.approve(request_id, always=False)

    async def cancel_run(self, run_id: str) -> None:
        if self._active_run_id != run_id:
            return
        if self.orchestrator is not None and self.orchestrator.session is not None:
            try:
                await self.orchestrator.session.cancel()
            except Exception:
                # Local cancellation still has to release the worker even when
                # the ACP process dies before accepting session/cancel.
                pass
        if self._active_task is not None and not self._active_task.done():
            task = self._active_task
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._active_run_id is not None:
            await self.cancel_run(self._active_run_id)
        if self._active_task is not None:
            await asyncio.gather(self._active_task, return_exceptions=True)
        if self._loop_task is not None and not self._loop_task.done():
            await self.queue.put(_WORKER_STOP)
            try:
                await asyncio.wait_for(self._loop_task, timeout=5)
            except asyncio.TimeoutError:
                self._loop_task.cancel()
                await asyncio.gather(self._loop_task, return_exceptions=True)
        await self._close_orchestrator()

    async def _run_loop(self) -> None:
        try:
            while True:
                item = await self.queue.get()
                try:
                    if item is _WORKER_STOP:
                        return
                    run = item
                    assert isinstance(run, _RunState)
                    if run.terminal:
                        continue
                    self._active_run_id = run.id
                    self._active_task = asyncio.create_task(
                        self._execute(run), name=f"kyn-run:{run.id}"
                    )
                    try:
                        await self._active_task
                    except Exception:
                        # A single corrupt/contended durable run must never
                        # kill the sole FIFO worker for this bot.
                        _logger.exception("Run worker failed for %s", run.id)
                finally:
                    self._active_task = None
                    self._active_run_id = None
                    self.queue.task_done()
        except asyncio.CancelledError:
            if self._active_task is not None and not self._active_task.done():
                self._active_task.cancel()
                await asyncio.gather(self._active_task, return_exceptions=True)
            raise

    async def _execute(self, run: _RunState) -> None:
        heartbeat: asyncio.Task[None] | None = None
        workspace_heartbeat: asyncio.Task[None] | None = None
        workspace_guard_id: str | None = None
        workspace_guard_acquired = False
        isolated_channel_session = run.actor.startswith("channel:")
        try:
            await self.engine._mark_started(run)
            if run.terminal or run.finishing:
                return
            if run.durable_lease is not None:
                heartbeat = asyncio.create_task(
                    self.engine._heartbeat_lease(run, asyncio.current_task()),
                    name=f"kyn-heartbeat:{run.id}",
                )
            if run.workspace_execution is not None:
                workspace_guard_id = run.workspace_execution.lease.run_id
                await self.engine._acquire_workspace_guard(workspace_guard_id)
                workspace_guard_acquired = True
            execution_cwd = await self.engine._prepare_execution(run)
            if isolated_channel_session and execution_cwd is None:
                execution_cwd = await self.engine._channel_session_cwd(run)
            if run.workspace_execution is not None:
                workspace_heartbeat = asyncio.create_task(
                    self.engine._heartbeat_workspace(run, asyncio.current_task()),
                    name=f"kyn-workspace-heartbeat:{run.id}",
                )
            orchestrator = await self._ensure_orchestrator(execution_cwd)
            execution_prompt = await self.engine._execution_prompt(run)
            async for event in orchestrator.run(execution_prompt):
                if event.kind == "permission":
                    await self.engine._apply_permission_policy(run, event, self)
                else:
                    await self.engine._append_event(run, event)
                if run.terminal:
                    return
            if not run.terminal:
                await self.engine._finish(run, "complete", stop_reason=run.stop_reason)
        except asyncio.CancelledError:
            if not run.terminal:
                await self.engine._finish(run, "cancelled")
            # A cancelled prompt may leave its final ACP response queued. Start
            # the next turn on a clean transport; BotOrchestrator will reload
            # the persisted Kiro session when this worker opens again.
            await self._close_orchestrator()
        except Exception as exc:
            if not run.terminal:
                await self.engine._finish(run, "failed", error=_error_text(exc))
            await self._close_orchestrator()
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
            if workspace_heartbeat is not None:
                workspace_heartbeat.cancel()
                await asyncio.gather(workspace_heartbeat, return_exceptions=True)
            if workspace_guard_id is not None and workspace_guard_acquired:
                await self.engine._release_workspace_guard(workspace_guard_id)
            if isolated_channel_session:
                # External source threads carry their own bounded evidence
                # bundle. Never let one Slack/GitHub/email thread inherit an
                # unrelated thread through the named bot's durable ACP session.
                await self._close_orchestrator()

    async def _ensure_orchestrator(self, cwd: str | None = None) -> _Orchestrator:
        if self.orchestrator is not None and self._orchestrator_cwd != cwd:
            await self._close_orchestrator()
        if self.orchestrator is None:
            orchestrator = self._orchestrator_factory(self.bot_name)
            try:
                if cwd is None:
                    await orchestrator.open(self.bot_name)
                else:
                    await orchestrator.open(self.bot_name, cwd=cwd)
            except BaseException:
                try:
                    await orchestrator.close()
                finally:
                    raise
            self.orchestrator = orchestrator
            self._orchestrator_cwd = cwd
        return self.orchestrator

    async def _close_orchestrator(self) -> None:
        orchestrator, self.orchestrator = self.orchestrator, None
        self._orchestrator_cwd = None
        if orchestrator is not None:
            try:
                await orchestrator.close()
            except Exception:
                pass


class Engine:
    """Long-running, in-memory run coordinator for persistent KYN bots.

    Each bot gets exactly one worker and therefore one active turn at a time.
    Workers are independent, so separate bots can run concurrently. Completed
    runs and individual event streams are retained within configurable bounds.
    """

    def __init__(
        self,
        *,
        store: Store | None = None,
        governance: GovernanceStore | None = None,
        plugins: PluginRegistry | None = None,
        run_repository: RunRepository | None = None,
        workspaces: WorkspaceManager | None = None,
        memory: SharedMemoryStore | None = None,
        interactions: InteractionStore | None = None,
        orchestrator_factory: OrchestratorFactory | None = None,
        max_runs: int = 500,
        max_events_per_run: int = 5_000,
        recover_on_start: bool = True,
    ) -> None:
        if max_runs < 1:
            raise ValueError("max_runs must be at least 1")
        if max_events_per_run < 1:
            raise ValueError("max_events_per_run must be at least 1")
        self._store = store
        self._plugins = plugins
        if orchestrator_factory is not None:
            self._orchestrator_factory = orchestrator_factory
        else:
            self._store = store or Store()
            self._plugins = plugins or PluginRegistry(self._store)
            self._orchestrator_factory = lambda _bot_name: BotOrchestrator(
                self._store, self._plugins
            )
        self._governance = governance
        self._run_repository = run_repository
        if self._governance is None and self._store is not None:
            from .governance import GovernanceStore as _GovernanceStore

            self._governance = _GovernanceStore(self._store)
        if self._run_repository is None and self._store is not None:
            self._run_repository = RunRepository(
                self._store, max_terminal_runs=max(max_runs * 10, max_runs)
            )
        self._workspaces = workspaces
        if self._workspaces is None and self._store is not None:
            self._workspaces = WorkspaceManager(
                self._store, self._store.home / "workspaces"
            )
        self._memory = memory
        if self._memory is None and self._store is not None:
            self._memory = SharedMemoryStore(self._store)
        self._interactions = interactions
        if self._interactions is None and self._store is not None:
            self._interactions = InteractionStore(self._store)
        self._max_runs = max_runs
        self._max_events_per_run = max_events_per_run
        self._recover_on_start = bool(recover_on_start)
        self._runs: OrderedDict[str, _RunState] = OrderedDict()
        self._workers: dict[str, BotWorker] = {}
        self._terminal_runs: deque[str] = deque()
        self._started = False
        self._closing = False
        self._store_lock_fd: int | None = None
        self._state_lock = asyncio.Lock()
        self._workspace_guard_lock = asyncio.Lock()
        self._workspace_guards: dict[str, _WorkspaceGuard] = {}

    async def start(self) -> None:
        async with self._state_lock:
            if self._closing:
                raise RuntimeError("engine has been closed")
            if self._started:
                return
            self._acquire_store_lock()
            try:
                if self._governance is not None and self._run_repository is not None:
                    await asyncio.to_thread(self._governance.reconcile_run_leases)
                if self._workspaces is not None:
                    await asyncio.to_thread(self._workspaces.recover_stale_leases)
                if self._run_repository is not None and self._recover_on_start:
                    await asyncio.to_thread(self._run_repository.recover_startup)
                    await self._restore_all_queued()
                self._started = True
            except BaseException:
                await self._close_workers()
                self._runs.clear()
                self._terminal_runs.clear()
                self._started = False
                self._release_store_lock()
                raise

    async def close(self) -> None:
        async with self._state_lock:
            if self._closing:
                return
            self._closing = True
        try:
            active = [run for run in self._runs.values() if not run.terminal]
            for run in active:
                worker = self._workers.get(run.bot_name)
                if worker is None or worker._active_run_id != run.id:
                    await self._finish(run, "cancelled")
            await self._close_workers()
            for run in active:
                if not run.terminal:
                    await self._finish(run, "cancelled")
        finally:
            self._started = False
            self._release_store_lock()

    async def _close_workers(self) -> None:
        workers = list(self._workers.values())
        self._workers.clear()
        if workers:
            await asyncio.gather(
                *(worker.close() for worker in workers),
                return_exceptions=True,
            )

    async def _channel_session_cwd(self, run: _RunState) -> str:
        if self._store is None:
            raise RuntimeError("isolated channel sessions require a persistent Store")
        bot = await asyncio.to_thread(self._store.get_bot, run.bot_name)
        if bot is None:
            raise RuntimeError(f"bot {run.bot_name!r} was not found")
        return bot.cwd

    async def _execution_prompt(self, run: _RunState) -> str:
        """Add host capabilities and bounded evidence without mutating run.message."""
        scope = local_scope(run.actor)
        context = ""
        if self._memory is not None and scope is not None:
            try:
                context = await asyncio.to_thread(
                    self._memory.render_context,
                    run.bot_name,
                    run.message,
                    exclude_scopes=(scope,),
                )
            except Exception:
                _logger.exception("Shared-memory retrieval failed for run %s", run.id)
        bot_names: tuple[str, ...] = ()
        if self._store is not None:
            try:
                bots = await asyncio.to_thread(self._store.list_bots)
                bot_names = tuple(bot.name for bot in bots)
            except Exception:
                _logger.exception("Bot inventory retrieval failed for run %s", run.id)
        return compose_execution_prompt(
            run.message,
            bot_names=bot_names,
            memory_context=context,
        )

    async def _restore_all_queued(self) -> None:
        assert self._run_repository is not None
        after_created_at: str | None = None
        after_run_id: str | None = None
        while True:
            batch = await asyncio.to_thread(
                self._run_repository.list_runs,
                status="queued",
                limit=1_000,
                after_created_at=after_created_at,
                after_run_id=after_run_id,
            )
            if not batch:
                return
            for durable in batch:
                await self._restore(durable)
            if len(batch) < 1_000:
                return
            after_created_at = batch[-1].created_at
            after_run_id = batch[-1].run_id

    def _acquire_store_lock(self) -> None:
        lock_store = self._store
        if lock_store is None and self._run_repository is not None:
            lock_store = self._run_repository.store
        if lock_store is None or self._store_lock_fd is not None:
            return
        path = lock_store.home / "controller.lock"
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if os.name == "posix":
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:  # pragma: no cover - Windows-specific fallback
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            os.close(descriptor)
            raise RuntimeError(
                "another KYN controller is already active for this data store"
            ) from exc
        self._store_lock_fd = descriptor

    def _release_store_lock(self) -> None:
        descriptor, self._store_lock_fd = self._store_lock_fd, None
        if descriptor is None:
            return
        try:
            if os.name == "posix":
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
            else:  # pragma: no cover - Windows-specific fallback
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(descriptor)

    async def submit(
        self,
        bot_name: str,
        message: str,
        *,
        actor: str = "api",
        execution: WorkspaceExecutionSpec | None = None,
    ) -> str:
        async with self._state_lock:
            if not self._started or self._closing:
                raise RuntimeError("start the engine before submitting runs")
            if not isinstance(bot_name, str) or not bot_name.strip():
                raise ValueError("bot_name must be a non-empty string")
            if not isinstance(message, str) or not message.strip():
                raise ValueError("message must be a non-empty string")
            if execution is not None and not isinstance(execution, WorkspaceExecutionSpec):
                raise ValueError("execution must be a WorkspaceExecutionSpec")
            if execution is not None and self._workspaces is None:
                raise RuntimeError("workspace execution requires a WorkspaceManager")

            run_id = uuid.uuid4().hex
            run = _RunState(
                id=run_id,
                bot_name=bot_name,
                message=message,
                max_events=self._max_events_per_run,
                actor=actor,
            )
            if self._run_repository is not None:
                await asyncio.to_thread(
                    self._run_repository.enqueue,
                    run_id,
                    bot_name,
                    message,
                    actor=actor,
                )
            if self._governance is not None:
                try:
                    run.governance_lease = await asyncio.to_thread(
                        self._governance.reserve_run,
                        bot_name,
                        run_id,
                        actor=actor,
                    )
                except BaseException:
                    if self._run_repository is not None:
                        await asyncio.to_thread(self._run_repository.cancel_queued, run_id)
                    raise
            if execution is not None:
                try:
                    assert self._workspaces is not None
                    run.workspace_execution = await asyncio.to_thread(
                        self._workspaces.prepare_execution,
                        execution,
                        run_id,
                        bot_name=bot_name,
                    )
                except BaseException:
                    if self._run_repository is not None:
                        await asyncio.to_thread(self._run_repository.cancel_queued, run_id)
                    if self._governance is not None and run.governance_lease is not None:
                        try:
                            await asyncio.to_thread(
                                self._governance.finish_run,
                                run.governance_lease,
                                "cancelled",
                                actor="engine",
                                reason="workspace_preparation_failed",
                            )
                        except Exception:
                            _logger.exception(
                                "Failed to release governance after workspace preparation"
                            )
                    raise
            self._runs[run_id] = run
            await self._enqueue(run)
            return run_id

    async def _restore(self, durable: Any) -> None:
        if durable.run_id in self._runs:
            return
        run = _RunState(
            id=durable.run_id,
            bot_name=durable.bot_name,
            message=durable.message,
            max_events=self._max_events_per_run,
            created_at=durable.created_at,
            actor=durable.actor,
        )
        if self._workspaces is not None:
            try:
                run.workspace_execution = await asyncio.to_thread(
                    self._workspaces.resume_execution, run.id
                )
                if (
                    run.workspace_execution is not None
                    and run.workspace_execution.workspace_state
                    in {"completed", "failed", "cancelled"}
                ):
                    lease = await asyncio.to_thread(
                        self._run_repository.claim,
                        run.id,
                        f"engine-{id(self)}:workspace-reconcile",
                        lease_seconds=_DURABLE_LEASE_SECONDS,
                    )
                    if lease is None:
                        await asyncio.to_thread(
                            self._run_repository.cancel_queued, run.id
                        )
                    else:
                        await asyncio.to_thread(
                            self._run_repository.finish,
                            run.id,
                            lease.token,
                            {
                                "completed": "complete",
                                "failed": "failed",
                                "cancelled": "cancelled",
                            }[run.workspace_execution.workspace_state],
                        )
                    return
            except Exception:
                await asyncio.to_thread(self._run_repository.cancel_queued, run.id)
                return
        if self._governance is not None:
            try:
                run.governance_lease = await asyncio.to_thread(
                    self._governance.reserve_run,
                    run.bot_name,
                    run.id,
                    actor="recovery",
                )
            except Exception:
                await asyncio.to_thread(self._run_repository.cancel_queued, run.id)
                return
        self._runs[run.id] = run
        await self._enqueue(run)

    async def _enqueue(self, run: _RunState) -> None:
        worker = self._workers.get(run.bot_name)
        if worker is None:
            worker = BotWorker(self, run.bot_name, self._orchestrator_factory)
            self._workers[run.bot_name] = worker
            worker.start()
        await worker.submit(run)

    async def get_run(self, run_id: str) -> dict[str, Any]:
        run = self._runs.get(run_id)
        if run is not None:
            return run.snapshot()
        durable = await self._get_durable_run(run_id)
        if durable is not None and durable.status in _TERMINAL_STATUSES:
            return _durable_snapshot(durable)
        raise RunNotFound(run_id)

    async def get_workspace_lease(self, run_id: str) -> WorkspaceLease:
        """Return a trusted lease for a harness coordinating multiple turns."""
        if self._workspaces is None:
            raise InvalidRunOperation("workspace manager is unavailable")
        execution = await asyncio.to_thread(self._workspaces.resume_execution, run_id)
        if execution is None:
            raise InvalidRunOperation("workspace execution binding is missing")
        if execution.workspace_state != "active":
            raise InvalidRunOperation("workspace execution is already finalized")
        return execution.lease

    async def subscribe(
        self, run_id: str, after_sequence: int = 0
    ) -> AsyncIterator[dict[str, Any]]:
        if after_sequence < 0:
            raise ValueError("after_sequence cannot be negative")
        run = self._runs.get(run_id)
        if run is None:
            durable = await self._get_durable_run(run_id)
            if durable is not None and durable.status in _TERMINAL_STATUSES:
                return
            raise RunNotFound(run_id)
        cursor = after_sequence

        while True:
            async with run.condition:
                while True:
                    available = [
                        event for event in run.events if int(event["sequence"]) > cursor
                    ]
                    if available or run.terminal:
                        break
                    await run.condition.wait()
                terminal = run.terminal

            for event in available:
                cursor = int(event["sequence"])
                yield _copy_json(event)
            if terminal and not any(
                int(event["sequence"]) > cursor for event in run.events
            ):
                return

    async def _get_durable_run(self, run_id: str) -> Any:
        if self._run_repository is None:
            return None
        return await asyncio.to_thread(self._run_repository.get, run_id)

    async def decide_permission(
        self,
        run_id: str,
        request_id: str | int,
        decision: PermissionDecision,
    ) -> dict[str, Any]:
        if decision not in {"once", "reject"}:
            raise ValueError("decision must be once or reject")
        run = self._get_state(run_id)
        token = str(request_id)
        async with run.permission_lock:
            pending = run.pending_permissions.get(token)
            if run.terminal or pending is None:
                raise InvalidRunOperation("permission request is not pending for this run")
            actual_request_id, canonical_tool_name = pending
            worker = self._workers.get(run.bot_name)
            if worker is None:
                raise InvalidRunOperation("the bot worker is no longer available")

            await worker.decide_permission(run.id, actual_request_id, decision)
            if self._interactions is not None:
                interactions = await asyncio.to_thread(
                    self._interactions.list,
                    bot_name=run.bot_name,
                    status="pending",
                    limit=500,
                )
                matching = next(
                    (
                        item
                        for item in interactions
                        if item.run_id == run.id and item.request_id == token
                    ),
                    None,
                )
                if matching is not None:
                    await asyncio.to_thread(
                        self._interactions.resolve,
                        matching.id,
                        decision,
                        actor=run.actor or "user",
                    )
            async with run.condition:
                run.pending_permissions.pop(token, None)
                if not run.pending_permissions and not run.terminal:
                    run.status = "running"
                run.condition.notify_all()
            await self._mark_durable_running(run)
            if self._governance is not None and canonical_tool_name:
                await asyncio.to_thread(
                    self._governance.record_permission_decision,
                    run.bot_name,
                    run.id,
                    token,
                    canonical_tool_name,
                    "deny" if decision == "reject" else "approve",
                    actor="user",
                    reason={
                        "once": "user_allowed_once",
                        "reject": "user_rejected",
                    }[decision],
                )
        return run.snapshot()

    async def cancel(self, run_id: str) -> dict[str, Any]:
        run = self._get_state(run_id)
        if run.terminal:
            return run.snapshot()
        worker = self._workers.get(run.bot_name)
        if worker is not None:
            await worker.cancel_run(run.id)
        if not run.terminal:
            await self._finish(run, "cancelled")
        return run.snapshot()

    def _get_state(self, run_id: str) -> _RunState:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise RunNotFound(run_id) from exc

    async def _mark_started(self, run: _RunState) -> None:
        async with run.lifecycle_lock:
            async with run.condition:
                if run.terminal or run.finishing:
                    return
            if self._run_repository is not None and run.durable_lease is None:
                lease = await asyncio.to_thread(
                    self._run_repository.claim,
                    run.id,
                    f"engine-{id(self)}:{run.bot_name}",
                    lease_seconds=_DURABLE_LEASE_SECONDS,
                )
                if lease is None:
                    raise InvalidRunOperation("durable run could not be claimed")
                run.durable_lease = lease
            async with run.condition:
                if run.terminal or run.finishing:
                    if self._run_repository is not None and run.durable_lease is not None:
                        await asyncio.to_thread(
                            self._run_repository.finish,
                            run.id,
                            run.durable_lease.token,
                            "cancelled",
                        )
                    return
                run.status = "running"
                run.started_at = _now()
                run.condition.notify_all()

    async def _heartbeat_lease(
        self,
        run: _RunState,
        owner_task: asyncio.Task[Any] | None,
    ) -> None:
        try:
            while True:
                await asyncio.sleep(_DURABLE_HEARTBEAT_SECONDS)
                async with run.lifecycle_lock:
                    if run.terminal or run.finishing or run.durable_lease is None:
                        return
                    run.durable_lease = await asyncio.to_thread(
                        self._run_repository.renew_lease,
                        run.id,
                        run.durable_lease.token,
                        lease_seconds=_DURABLE_LEASE_SECONDS,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            _logger.exception("Durable lease heartbeat failed for %s", run.id)
            if owner_task is not None and not owner_task.done():
                owner_task.cancel()

    async def _prepare_execution(self, run: _RunState) -> str | None:
        execution = run.workspace_execution
        if execution is None:
            return None
        if self._workspaces is None:
            raise InvalidRunOperation("workspace manager is unavailable")
        lease = await asyncio.to_thread(
            self._workspaces.validate_lease, execution.lease
        )
        run.workspace_execution = WorkspaceExecution(
            lease,
            execution.artifact_paths,
            execution.auto_finalize,
            execution.lease_seconds,
            "active",
        )
        return lease.path

    async def _acquire_workspace_guard(self, workspace_run_id: str) -> None:
        async with self._workspace_guard_lock:
            guard = self._workspace_guards.get(workspace_run_id)
            if guard is None:
                guard = _WorkspaceGuard()
                self._workspace_guards[workspace_run_id] = guard
            guard.users += 1
        try:
            await guard.lock.acquire()
        except BaseException:
            async with self._workspace_guard_lock:
                guard.users -= 1
                if guard.users == 0:
                    self._workspace_guards.pop(workspace_run_id, None)
            raise

    async def _release_workspace_guard(self, workspace_run_id: str) -> None:
        async with self._workspace_guard_lock:
            guard = self._workspace_guards.get(workspace_run_id)
            if guard is None:
                return
            guard.lock.release()
            guard.users -= 1
            if guard.users == 0:
                self._workspace_guards.pop(workspace_run_id, None)

    async def _heartbeat_workspace(
        self,
        run: _RunState,
        owner_task: asyncio.Task[Any] | None,
    ) -> None:
        try:
            while True:
                execution = run.workspace_execution
                if execution is None:
                    return
                await asyncio.sleep(
                    min(
                        _WORKSPACE_HEARTBEAT_SECONDS,
                        max(execution.lease_seconds / 3, 0.01),
                    )
                )
                async with run.lifecycle_lock:
                    execution = run.workspace_execution
                    if run.terminal or run.finishing or execution is None:
                        return
                    assert self._workspaces is not None
                    lease = await asyncio.to_thread(
                        self._workspaces.heartbeat,
                        execution.lease,
                        lease_seconds=execution.lease_seconds,
                    )
                    run.workspace_execution = WorkspaceExecution(
                        lease,
                        execution.artifact_paths,
                        execution.auto_finalize,
                        execution.lease_seconds,
                        "active",
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            _logger.exception("Workspace lease heartbeat failed for %s", run.id)
            if owner_task is not None and not owner_task.done():
                owner_task.cancel()

    async def _append_event(self, run: _RunState, event: Event) -> None:
        async with run.condition:
            if run.terminal or run.finishing:
                return
            record = _event_record(run.next_sequence, event)
            run.next_sequence += 1
            run.events.append(record)
            if event.kind == "complete":
                run.stop_reason = event.stop_reason
            run.condition.notify_all()

    async def _apply_permission_policy(
        self,
        run: _RunState,
        event: Event,
        worker: BotWorker,
    ) -> None:
        """Apply deterministic policy only to Kiro's canonical tool identity."""
        if event.kind != "permission":
            return
        token = str(event.request_id)
        async with run.permission_lock:
            if run.terminal:
                return
            run.pending_permissions[token] = (
                event.request_id,
                event.tool_name or "unknown",
            )
        plugin_denied = False
        decision_reason = ""
        canonical_tool_name = event.tool_name or "unknown"
        if self._plugins is not None:
            # Built-in Kiro tools have a canonical tool name but no MCP server.
            # Apply the plugin registry only to MCP-originated calls; otherwise
            # every ordinary filesystem or terminal request would be denied.
            if not event.tool_name:
                plugin_denied = True
                decision_reason = "plugin_identity_missing"
            elif event.mcp_server_name:
                plugin = await asyncio.to_thread(
                    self._plugins.get_plugin, event.mcp_server_name
                )
                if plugin is None:
                    plugin_denied = True
                    decision_reason = "plugin_not_registered"
                else:
                    plugin_denied = not await asyncio.to_thread(
                        self._plugins.tool_allowed,
                        run.bot_name,
                        event.mcp_server_name,
                        event.tool_name,
                    )
                    if plugin_denied:
                        decision_reason = "plugin_tool_denied"
        if plugin_denied:
            decision_name = "deny"
        elif self._governance is not None and event.tool_name:
            policy_decision = await asyncio.to_thread(
                self._governance.evaluate_tool,
                run.bot_name,
                event.tool_name,
                token,
                event.title,
            )
            decision_name = policy_decision.decision
            decision_reason = policy_decision.reason
        else:
            decision_name, decision_reason = "ask", "approval_required"
        if decision_name == "ask":
            async with run.condition:
                run.status = "waiting_permission"
                run.condition.notify_all()
            interaction_id = ""
            if self._interactions is not None:
                interaction = await asyncio.to_thread(
                    self._interactions.create_permission,
                    run_id=run.id,
                    bot_name=run.bot_name,
                    actor=run.actor,
                    request_id=token,
                    title=event.title or "Tool permission requested",
                    tool_name=event.tool_name or "unknown",
                )
                interaction_id = interaction.id
            await self._append_event(
                run,
                Event(
                    kind="interaction_required",
                    title=event.title,
                    tool_call_id=event.tool_call_id,
                    request_id=event.request_id,
                    options=event.options,
                    tool_name=event.tool_name,
                    mcp_server_name=event.mcp_server_name,
                    interaction_id=interaction_id,
                ),
            )
            if self._run_repository is not None and run.durable_lease is not None:
                await asyncio.to_thread(
                    self._run_repository.mark_waiting_permission,
                    run.id,
                    run.durable_lease.token,
                )
            if self._governance is not None:
                await asyncio.to_thread(
                    self._governance.record_permission_decision,
                    run.bot_name,
                    run.id,
                    token,
                    event.tool_name,
                    "ask",
                    actor="policy",
                    reason=decision_reason,
                )
            return

        async with run.permission_lock:
            pending = run.pending_permissions.get(token)
            if pending is None or run.terminal:
                return
            actual_request_id, canonical_tool_name = pending
            action: PermissionDecision = (
                "reject" if decision_name == "deny" else "once"
            )
            await worker.decide_permission(run.id, actual_request_id, action)
            async with run.condition:
                run.pending_permissions.pop(token, None)
                if not run.pending_permissions and not run.terminal:
                    run.status = "running"
                run.condition.notify_all()
            await self._mark_durable_running(run)
            if self._governance is not None:
                await asyncio.to_thread(
                    self._governance.record_permission_decision,
                    run.bot_name,
                    run.id,
                    token,
                    canonical_tool_name,
                    decision_name,
                    actor="policy",
                    reason=decision_reason,
                )

    async def _mark_durable_running(self, run: _RunState) -> None:
        if self._run_repository is not None and run.durable_lease is not None:
            await asyncio.to_thread(
                self._run_repository.mark_running,
                run.id,
                run.durable_lease.token,
            )

    async def _finish(
        self,
        run: _RunState,
        status: Literal["complete", "failed", "cancelled"],
        *,
        stop_reason: str = "",
        error: str = "",
    ) -> None:
        async with run.lifecycle_lock:
            async with run.condition:
                if run.terminal:
                    return
                run.finishing = True
                if stop_reason:
                    run.stop_reason = stop_reason
                run.error = error
                run.finished_at = _now()
                run.pending_permissions.clear()
            if self._interactions is not None:
                await asyncio.to_thread(self._interactions.expire_run, run.id)
            try:
                execution = run.workspace_execution
                if (
                    execution is not None
                    and execution.auto_finalize
                    and self._workspaces is not None
                ):
                    outcome = {
                        "complete": "completed",
                        "failed": "failed",
                        "cancelled": "cancelled",
                    }[status]
                    try:
                        manifest = await asyncio.to_thread(
                            self._workspaces.finalize,
                            execution.lease,
                            outcome,
                            artifact_paths=execution.artifact_paths,
                        )
                    except Exception as exc:
                        current = await asyncio.to_thread(
                            self._workspaces.get_manifest,
                            execution.lease.run_id,
                        )
                        if current is not None and current.state in {
                            "completed",
                            "failed",
                            "cancelled",
                        }:
                            manifest = current
                            status = {
                                "completed": "complete",
                                "failed": "failed",
                                "cancelled": "cancelled",
                            }[current.state]
                        else:
                            manifest = await asyncio.to_thread(
                                self._workspaces.finalize_failure,
                                execution.lease,
                                exc,
                            )
                            workspace_error = _error_text(exc)
                            error = (
                                f"{error}; {workspace_error}"
                                if error
                                else workspace_error
                            )
                            if status == "complete":
                                status = "failed"
                    run.workspace_manifest = manifest.summary()
                if self._run_repository is not None:
                    if run.durable_lease is not None:
                        await asyncio.to_thread(
                            self._run_repository.finish,
                            run.id,
                            run.durable_lease.token,
                            status,
                        )
                    elif status == "cancelled":
                        await asyncio.to_thread(
                            self._run_repository.cancel_queued,
                            run.id,
                        )
            except BaseException:
                async with run.condition:
                    run.finishing = False
                    run.finished_at = None
                    run.condition.notify_all()
                raise
            if self._governance is not None and run.governance_lease is not None:
                try:
                    await asyncio.to_thread(
                        self._governance.finish_run,
                        run.governance_lease,
                        status,
                        actor="engine",
                        reason={
                            "complete": "run_completed",
                            "failed": "run_failed",
                            "cancelled": "run_cancelled",
                        }[status],
                    )
                except Exception:
                    # The durable ledger is authoritative. Startup reconciliation
                    # releases this governance lease if this second commit fails.
                    _logger.exception("Failed to finalize governance lease for run %s", run.id)
            if status == "complete":
                await self._record_memory(run)
            async with run.condition:
                run.status = status
                run.finishing = False
                run.condition.notify_all()
        self._terminal_runs.append(run.id)
        self._prune_runs()

    async def _record_memory(self, run: _RunState) -> None:
        scope = local_scope(run.actor)
        if self._memory is None or scope is None:
            return
        response = _response_text(run.events)
        if not response:
            return
        try:
            await asyncio.to_thread(
                self._memory.record,
                run.bot_name,
                scope,
                run.actor,
                run.message,
                response,
                event_id=f"run:{run.id}",
                metadata={"run_id": run.id},
                created_at=run.finished_at,
            )
        except Exception:
            # Memory is a continuity aid, not part of the run's commit point.
            _logger.exception("Shared-memory recording failed for run %s", run.id)

    def _prune_runs(self) -> None:
        while len(self._runs) > self._max_runs and self._terminal_runs:
            run_id = self._terminal_runs.popleft()
            run = self._runs.get(run_id)
            if run is not None and run.terminal:
                self._runs.pop(run_id, None)


def _event_record(sequence: int, event: Event) -> dict[str, Any]:
    request_id: str | int = event.request_id
    if not isinstance(request_id, (str, int)):
        request_id = str(request_id)
    return {
        "sequence": sequence,
        "kind": str(event.kind),
        "text": str(event.text),
        "title": str(event.title),
        "tool_call_id": str(event.tool_call_id),
        "request_id": request_id,
        "options": _json_safe(event.options),
        "stop_reason": str(event.stop_reason),
        "tool_name": str(event.tool_name),
        "mcp_server_name": str(event.mcp_server_name),
        "interaction_id": str(event.interaction_id),
    }


def _durable_snapshot(run: Any) -> dict[str, Any]:
    return {
        "id": run.run_id,
        "bot_name": run.bot_name,
        "message": run.message,
        "actor": run.actor,
        "status": run.status,
        "stop_reason": "",
        "error": "",
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "events": [],
    }


def _response_text(events: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for event in events:
        if event.get("kind") not in {"text", "message", "assistant", "assistant_message"}:
            continue
        text = event.get("text")
        if isinstance(text, str) and text:
            chunks.append(text)
    return "".join(chunks).strip()


def _json_safe(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError, OverflowError):
        return str(value)


def _copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _error_text(exc: Exception) -> str:
    message = str(exc).strip()
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
