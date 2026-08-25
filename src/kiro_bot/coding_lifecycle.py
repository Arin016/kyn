"""Durable, isolated coding executions composed from Kiro Bot primitives.

The lifecycle deliberately stops at a human handoff.  Agents may build,
repair, and review inside one detached worktree, while the harness owns the
verification commands, budgets, persistence, and final artifact manifest.
It never pushes, merges, publishes, or opens a pull request.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import signal
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .coding_workflow import (
    BuildRequest,
    BuildResult,
    CancellationToken,
    CodingWorkflow,
    CodingWorkflowCallbacks,
    CodingWorkflowRequest,
    CommandResult,
    CommandSpec,
    ExecutionContext,
    GateRule,
    RepairRequest,
    RepairResult,
    ReviewRequest,
    ReviewResult,
    WorkflowArtifact,
    WorkflowBudget,
    WorkspaceRef,
)
from .store import Store
from .workspaces import (
    WorkspaceExecutionSpec,
    WorkspaceLease,
    WorkspaceManager,
)


ExecutionStatus = Literal[
    "queued", "running", "awaiting_handoff", "ready", "failed", "cancelled"
]
_TERMINAL = frozenset({"ready", "failed", "cancelled"})
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+~-]{0,159}$")


class CodingLifecycleError(RuntimeError):
    pass


class CodingExecutionNotFound(KeyError):
    pass


class CodingExecutionConflict(CodingLifecycleError):
    pass


@dataclass(frozen=True, slots=True)
class CheckSpec:
    name: str
    argv: tuple[str, ...]
    timeout_seconds: float = 600.0

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not name or len(name) > 100:
            raise ValueError("check name must contain 1 to 100 characters")
        CommandSpec(tuple(self.argv), label=name, timeout_seconds=self.timeout_seconds)


@dataclass(frozen=True, slots=True)
class CodingExecutionSpec:
    repo_path: str
    task: str
    builder_bot: str
    reviewer_bot: str
    checks: tuple[CheckSpec, ...]
    ref: str = "HEAD"
    max_repairs: int = 1
    timeout_seconds: float = 1800.0

    def __post_init__(self) -> None:
        if not self.repo_path.strip():
            raise ValueError("repo_path is required")
        if not self.task.strip() or len(self.task) > 100_000:
            raise ValueError("task must contain 1 to 100000 characters")
        if not self.builder_bot.strip() or not self.reviewer_bot.strip():
            raise ValueError("builder_bot and reviewer_bot are required")
        if self.builder_bot == self.reviewer_bot:
            raise ValueError("reviewer_bot must be independent from builder_bot")
        if not self.checks:
            raise ValueError("at least one deterministic check is required")
        if len(self.checks) > 20:
            raise ValueError("at most 20 checks are allowed")
        if not 0 <= self.max_repairs <= 3:
            raise ValueError("max_repairs must be between 0 and 3")
        if not 30 <= self.timeout_seconds <= 86_400:
            raise ValueError("timeout_seconds must be between 30 and 86400")

    def payload(self) -> dict[str, Any]:
        return {
            "repo_path": str(Path(self.repo_path).expanduser().resolve()),
            "ref": self.ref,
            "task": self.task,
            "builder_bot": self.builder_bot,
            "reviewer_bot": self.reviewer_bot,
            "checks": [
                {
                    "name": check.name,
                    "argv": list(check.argv),
                    "timeout_seconds": check.timeout_seconds,
                }
                for check in self.checks
            ],
            "max_repairs": self.max_repairs,
            "timeout_seconds": self.timeout_seconds,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "CodingExecutionSpec":
        return cls(
            repo_path=str(payload["repo_path"]),
            ref=str(payload.get("ref") or "HEAD"),
            task=str(payload["task"]),
            builder_bot=str(payload["builder_bot"]),
            reviewer_bot=str(payload["reviewer_bot"]),
            checks=tuple(
                CheckSpec(
                    name=str(item["name"]),
                    argv=tuple(str(part) for part in item["argv"]),
                    timeout_seconds=float(item.get("timeout_seconds") or 600),
                )
                for item in payload["checks"]
            ),
            max_repairs=int(payload.get("max_repairs") or 0),
            timeout_seconds=float(payload.get("timeout_seconds") or 1800),
        )


@dataclass(frozen=True, slots=True)
class CodingExecution:
    id: str
    idempotency_key: str
    spec: CodingExecutionSpec
    spec_sha256: str
    status: ExecutionStatus
    version: int
    workspace_run_id: str
    active_run_id: str
    result: Mapping[str, Any] | None
    error: str
    created_at: str
    updated_at: str
    finished_at: str

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "idempotency_key": self.idempotency_key,
            "spec": self.spec.payload(),
            "spec_sha256": self.spec_sha256,
            "status": self.status,
            "version": self.version,
            "workspace_run_id": self.workspace_run_id,
            "active_run_id": self.active_run_id,
            "result": _json_safe(self.result),
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
        }


class CodingExecutionStore:
    """SQLite acceptance ledger and generation-safe handoff state."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self._migrate()

    def create_or_get(
        self, spec: CodingExecutionSpec, idempotency_key: str
    ) -> tuple[CodingExecution, bool]:
        key = _idempotency_key(idempotency_key)
        payload = _canonical_json(spec.payload())
        digest = hashlib.sha256(payload.encode()).hexdigest()
        now = _now()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM coding_executions WHERE idempotency_key = ?", (key,)
            ).fetchone()
            if existing is not None:
                if existing["spec_sha256"] != digest:
                    raise CodingExecutionConflict(
                        "idempotency key is already bound to a different coding specification"
                    )
                return _execution(existing), False
            execution_id = f"coding-{uuid.uuid4().hex}"
            db.execute(
                """
                INSERT INTO coding_executions(
                    id, idempotency_key, spec_json, spec_sha256, status, version,
                    workspace_run_id, active_run_id, result_json, error,
                    created_at, updated_at, finished_at
                ) VALUES (?, ?, ?, ?, 'queued', 1, ?, '', '', '', ?, ?, '')
                """,
                (execution_id, key, payload, digest, execution_id, now, now),
            )
            row = db.execute(
                "SELECT * FROM coding_executions WHERE id = ?", (execution_id,)
            ).fetchone()
        assert row is not None
        return _execution(row), True

    def get(self, execution_id: str) -> CodingExecution | None:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM coding_executions WHERE id = ?", (execution_id,)
            ).fetchone()
        return _execution(row) if row is not None else None

    def list(self, *, limit: int = 100) -> list[CodingExecution]:
        bounded = min(max(int(limit), 1), 500)
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT * FROM coding_executions ORDER BY created_at DESC, id DESC LIMIT ?",
                (bounded,),
            ).fetchall()
        return [_execution(row) for row in rows]

    def recoverable(self) -> list[CodingExecution]:
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT * FROM coding_executions WHERE status IN ('queued', 'running') ORDER BY created_at, id"
            ).fetchall()
        return [_execution(row) for row in rows]

    def set_running(self, execution_id: str) -> CodingExecution:
        return self._update(execution_id, {"queued", "running"}, "running")

    def set_active_run(self, execution_id: str, run_id: str) -> CodingExecution:
        now = _now()
        with self.store.connect() as db:
            cursor = db.execute(
                """
                UPDATE coding_executions
                SET active_run_id = ?, updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (run_id, now, execution_id),
            )
            if cursor.rowcount != 1:
                raise CodingLifecycleError("coding execution is no longer running")
        return self.require(execution_id)

    def finish(
        self,
        execution_id: str,
        status: Literal["awaiting_handoff", "failed", "cancelled"],
        *,
        result: Mapping[str, Any] | None = None,
        error: str = "",
    ) -> CodingExecution:
        if status not in {"awaiting_handoff", "failed", "cancelled"}:
            raise ValueError("invalid coding completion status")
        now = _now()
        result_json = _canonical_json(_json_safe(result)) if result is not None else ""
        with self.store.connect() as db:
            cursor = db.execute(
                """
                UPDATE coding_executions
                SET status = ?, version = version + 1, active_run_id = '',
                    result_json = ?, error = ?, updated_at = ?, finished_at = ?
                WHERE id = ? AND status IN ('queued', 'running')
                """,
                (status, result_json, _bounded(error, 1000), now, now, execution_id),
            )
            if cursor.rowcount != 1:
                current = self.get(execution_id)
                if current is None:
                    raise CodingExecutionNotFound(execution_id)
                return current
        return self.require(execution_id)

    def approve(self, execution_id: str, expected_version: int) -> CodingExecution:
        now = _now()
        with self.store.connect() as db:
            cursor = db.execute(
                """
                UPDATE coding_executions
                SET status = 'ready', version = version + 1, updated_at = ?, finished_at = ?
                WHERE id = ? AND status = 'awaiting_handoff' AND version = ?
                """,
                (now, now, execution_id, int(expected_version)),
            )
            if cursor.rowcount != 1:
                raise CodingExecutionConflict(
                    "handoff changed or is not awaiting approval; refresh before approving"
                )
        return self.require(execution_id)

    def cancel(self, execution_id: str) -> CodingExecution:
        now = _now()
        with self.store.connect() as db:
            cursor = db.execute(
                """
                UPDATE coding_executions
                SET status = 'cancelled', version = version + 1,
                    active_run_id = '', updated_at = ?, finished_at = ?
                WHERE id = ? AND status IN ('queued', 'running', 'awaiting_handoff')
                """,
                (now, now, execution_id),
            )
            if cursor.rowcount != 1:
                current = self.get(execution_id)
                if current is None:
                    raise CodingExecutionNotFound(execution_id)
                return current
        return self.require(execution_id)

    def require(self, execution_id: str) -> CodingExecution:
        execution = self.get(execution_id)
        if execution is None:
            raise CodingExecutionNotFound(execution_id)
        return execution

    def _update(
        self, execution_id: str, from_statuses: set[str], status: ExecutionStatus
    ) -> CodingExecution:
        now = _now()
        placeholders = ",".join("?" for _ in from_statuses)
        with self.store.connect() as db:
            cursor = db.execute(
                f"""
                UPDATE coding_executions
                SET status = ?, version = version + 1, updated_at = ?
                WHERE id = ? AND status IN ({placeholders})
                """,
                (status, now, execution_id, *sorted(from_statuses)),
            )
            if cursor.rowcount != 1:
                raise CodingLifecycleError("coding execution transition was rejected")
        return self.require(execution_id)

    def _migrate(self) -> None:
        with self.store.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS coding_executions (
                    id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    spec_json TEXT NOT NULL,
                    spec_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'queued', 'running', 'awaiting_handoff', 'ready', 'failed', 'cancelled'
                    )),
                    version INTEGER NOT NULL,
                    workspace_run_id TEXT NOT NULL UNIQUE,
                    active_run_id TEXT NOT NULL DEFAULT '',
                    result_json TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS coding_executions_status
                    ON coding_executions(status, created_at);
                """
            )


class CodingLifecycleController:
    """Compose Engine, worktrees, deterministic checks, and human handoff."""

    def __init__(
        self,
        store: CodingExecutionStore,
        engine: Any,
        workspaces: WorkspaceManager,
    ) -> None:
        self.store = store
        self.engine = engine
        self.workspaces = workspaces
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._tokens: dict[str, CancellationToken] = {}
        self._closing = False

    async def start(self) -> None:
        self._closing = False
        for execution in await asyncio.to_thread(self.store.recoverable):
            self._launch(execution.id)

    async def close(self) -> None:
        self._closing = True
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def submit(
        self,
        spec: CodingExecutionSpec,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if self._closing:
            raise CodingLifecycleError("coding lifecycle controller is closed")
        self._require_bots(spec)
        execution, created = await asyncio.to_thread(
            self.store.create_or_get, spec, idempotency_key
        )
        if created or execution.status in {"queued", "running"}:
            self._launch(execution.id)
        return execution.snapshot()

    async def get(self, execution_id: str) -> dict[str, Any]:
        return (await asyncio.to_thread(self.store.require, execution_id)).snapshot()

    async def list(self) -> list[dict[str, Any]]:
        return [item.snapshot() for item in await asyncio.to_thread(self.store.list)]

    async def approve(self, execution_id: str, expected_version: int) -> dict[str, Any]:
        return (
            await asyncio.to_thread(self.store.approve, execution_id, expected_version)
        ).snapshot()

    async def cancel(self, execution_id: str) -> dict[str, Any]:
        execution = await asyncio.to_thread(self.store.require, execution_id)
        if execution.status in _TERMINAL or execution.status == "awaiting_handoff":
            if execution.status == "awaiting_handoff":
                execution = await asyncio.to_thread(
                    self.store.cancel, execution_id
                )
            return execution.snapshot()
        token = self._tokens.get(execution_id)
        if token is not None:
            token.cancel("cancelled by user")
        if execution.active_run_id:
            try:
                await self.engine.cancel(execution.active_run_id)
            except (KeyError, RuntimeError):
                pass
        execution = await asyncio.to_thread(self.store.cancel, execution_id)
        return execution.snapshot()

    def _launch(self, execution_id: str) -> None:
        existing = self._tasks.get(execution_id)
        if existing is not None and not existing.done():
            return
        task = asyncio.create_task(
            self._run(execution_id), name=f"kiro-coding:{execution_id}"
        )
        self._tasks[execution_id] = task
        task.add_done_callback(lambda done, key=execution_id: self._done(key, done))

    def _done(self, execution_id: str, task: asyncio.Task[None]) -> None:
        self._tasks.pop(execution_id, None)
        self._tokens.pop(execution_id, None)
        if not task.cancelled():
            task.exception()  # observe unexpected failures; _run persists them

    async def _run(self, execution_id: str) -> None:
        token = CancellationToken()
        self._tokens[execution_id] = token
        execution = await asyncio.to_thread(self.store.set_running, execution_id)
        spec = execution.spec
        workspace_execution = None
        try:
            workspace_execution = await asyncio.to_thread(
                self.workspaces.resume_execution, execution.workspace_run_id
            )
            if workspace_execution is None:
                workspace_execution = await asyncio.to_thread(
                    self.workspaces.prepare_execution,
                    WorkspaceExecutionSpec(
                        repo_path=spec.repo_path,
                        ref=spec.ref,
                        lease_seconds=max(spec.timeout_seconds + 300, 600),
                        auto_finalize=False,
                    ),
                    execution.workspace_run_id,
                    bot_name=spec.builder_bot,
                )
            lease = workspace_execution.lease
            workspace_ref = WorkspaceRef(
                execution.workspace_run_id,
                lease.path,
                {"base_commit": lease.commit, "repo_path": lease.repo_path},
            )
            callbacks = self._callbacks(execution_id, spec, lease)
            workflow = CodingWorkflow(callbacks)
            commands = tuple(
                CommandSpec(
                    check.argv,
                    label=check.name,
                    timeout_seconds=check.timeout_seconds,
                )
                for check in spec.checks
            )
            rules = tuple(
                GateRule(command.argv, label=command.label) for command in commands
            )
            result = await workflow.run(
                CodingWorkflowRequest(
                    execution_id,
                    commands,
                    rules,
                    WorkflowBudget(
                        max_repair_attempts=spec.max_repairs,
                        max_commands=max(len(commands) * (spec.max_repairs + 1), 1),
                        timeout_seconds=spec.timeout_seconds,
                    ),
                    cancellation=token,
                    workspace=workspace_ref,
                )
            )
            snapshot = result.snapshot()
            if result.status.value == "completed":
                await asyncio.to_thread(
                    self.store.finish,
                    execution_id,
                    "awaiting_handoff",
                    result=snapshot,
                )
            else:
                outcome = "cancelled" if result.status.value == "cancelled" else "failed"
                await self._finalize_if_active(lease, outcome)
                await asyncio.to_thread(
                    self.store.finish,
                    execution_id,
                    outcome,
                    result=snapshot,
                    error=result.error,
                )
        except BaseException as exc:
            if isinstance(exc, asyncio.CancelledError):
                raise
            if workspace_execution is not None:
                await self._finalize_if_active(workspace_execution.lease, "failed")
            await asyncio.to_thread(
                self.store.finish,
                execution_id,
                "failed",
                error=f"{type(exc).__name__}: {exc}"[:1000],
            )

    def _callbacks(
        self,
        execution_id: str,
        spec: CodingExecutionSpec,
        lease: WorkspaceLease,
    ) -> CodingWorkflowCallbacks:
        async def build(_request: BuildRequest) -> BuildResult:
            summary = await self._agent_turn(
                execution_id,
                spec.builder_bot,
                _build_prompt(spec.task),
                lease,
            )
            return BuildResult(summary, await self._changed_files(lease))

        async def execute(command: CommandSpec, context: ExecutionContext) -> CommandResult:
            return await _run_command(command, Path(lease.path), context.cancellation)

        async def repair(request: RepairRequest) -> RepairResult:
            prompt = _repair_prompt(spec.task, request)
            summary = await self._agent_turn(
                execution_id, spec.builder_bot, prompt, lease
            )
            return RepairResult(summary, await self._changed_files(lease))

        async def review(request: ReviewRequest) -> ReviewResult:
            before = await asyncio.to_thread(_git_fingerprint, Path(lease.path))
            prompt = await asyncio.to_thread(
                _review_prompt, spec.task, Path(lease.path), request
            )
            response = await self._agent_turn(
                execution_id, spec.reviewer_bot, prompt, lease
            )
            after = await asyncio.to_thread(_git_fingerprint, Path(lease.path))
            if before != after:
                return ReviewResult(
                    False,
                    "Reviewer mutated the candidate workspace",
                    blocking_findings=("reviewer changed the worktree during read-only review",),
                )
            return _parse_review(response)

        async def artifact(_request: Any) -> WorkflowArtifact:
            manifest = await asyncio.to_thread(
                self.workspaces.finalize, lease, "completed"
            )
            return WorkflowArtifact(
                "Verified patch is ready for human handoff",
                tuple(item.path for item in manifest.artifacts),
                manifest.summary(),
            )

        return CodingWorkflowCallbacks(build, execute, repair, review, artifact)

    async def _agent_turn(
        self,
        execution_id: str,
        bot_name: str,
        prompt: str,
        lease: WorkspaceLease,
    ) -> str:
        run_id = await self.engine.submit(
            bot_name,
            prompt,
            actor="coding",
            execution=WorkspaceExecutionSpec(
                lease=lease,
                lease_seconds=3600,
                auto_finalize=False,
            ),
        )
        await asyncio.to_thread(self.store.set_active_run, execution_id, run_id)
        async for _event in self.engine.subscribe(run_id):
            pass
        snapshot = await self.engine.get_run(run_id)
        if snapshot.get("status") != "complete":
            raise CodingLifecycleError(
                str(snapshot.get("error") or f"Kiro run ended as {snapshot.get('status')}")
            )
        text = "".join(
            str(event.get("text") or "")
            for event in snapshot.get("events", [])
            if event.get("kind") == "text"
        ).strip()
        return text or "Kiro turn completed"

    async def _changed_files(self, lease: WorkspaceLease) -> tuple[str, ...]:
        artifacts = await asyncio.to_thread(self.workspaces.enumerate_artifacts, lease)
        return tuple(item.path for item in artifacts)

    async def _finalize_if_active(self, lease: WorkspaceLease, outcome: str) -> None:
        manifest = await asyncio.to_thread(self.workspaces.get_manifest, lease.run_id)
        if manifest is not None and manifest.state == "active":
            try:
                await asyncio.to_thread(self.workspaces.finalize, lease, outcome)
            except Exception:
                pass

    def _require_bots(self, spec: CodingExecutionSpec) -> None:
        for name in (spec.builder_bot, spec.reviewer_bot):
            if self.store.store.get_bot(name) is None:
                raise ValueError(f"unknown bot {name!r}")


async def _run_command(
    command: CommandSpec,
    cwd: Path,
    cancellation: CancellationToken,
) -> CommandResult:
    """Run one argv-only check with a bounded environment and process group."""
    started = time.monotonic()
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "LANG", "LC_ALL", "TERM", "TMPDIR", "SYSTEMROOT"}
    }
    process = await asyncio.create_subprocess_exec(
        *command.argv,
        cwd=str(cwd),
        env=environment,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=os.name == "posix",
    )
    communicate = asyncio.create_task(process.communicate())
    cancelled = asyncio.create_task(cancellation.wait())
    timed_out = False
    try:
        timeout = command.timeout_seconds or 600
        done, _ = await asyncio.wait(
            {communicate, cancelled}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
        )
        if cancelled in done:
            raise asyncio.CancelledError
        if communicate not in done:
            timed_out = True
            await _stop_process(process)
            stdout, stderr = await communicate
        else:
            stdout, stderr = await communicate
    except asyncio.CancelledError:
        await _stop_process(process)
        communicate.cancel()
        await asyncio.gather(communicate, return_exceptions=True)
        raise
    finally:
        cancelled.cancel()
        await asyncio.gather(cancelled, return_exceptions=True)
    return CommandResult(
        None if timed_out else process.returncode,
        stdout.decode("utf-8", "replace"),
        stderr.decode("utf-8", "replace"),
        timed_out,
        time.monotonic() - started,
    )


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:  # pragma: no cover - Windows
            process.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=2)
    except asyncio.TimeoutError:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:  # pragma: no cover - Windows
                process.kill()
        except ProcessLookupError:
            pass
        await process.wait()


def _build_prompt(task: str) -> str:
    return (
        "Work only inside the current isolated Git worktree. Implement the task below, "
        "including relevant tests. Do not push, merge, rebase, publish, open a pull "
        "request, or change the source checkout. If partial work already exists, inspect "
        "and continue it safely. Finish with a concise summary of changes and risks.\n\n"
        f"TASK:\n{task}"
    )


def _repair_prompt(task: str, request: RepairRequest) -> str:
    evidence = [failure.snapshot() for failure in request.failures]
    if request.review is not None:
        evidence.append(
            {
                "review_summary": request.review.summary,
                "blocking_findings": list(request.review.blocking_findings),
            }
        )
    return (
        "Work only inside the current isolated Git worktree. Repair the existing candidate "
        "against the bounded evidence below. Preserve correct work. Do not push, merge, "
        "rebase, publish, or open a pull request.\n\n"
        f"ORIGINAL TASK:\n{task}\n\nEVIDENCE:\n{_canonical_json(evidence)}"
    )


def _review_prompt(task: str, cwd: Path, request: ReviewRequest) -> str:
    patch = _git_output(cwd, "diff", "--no-ext-diff", "--unified=3", "HEAD")
    if len(patch) > 80_000:
        patch = patch[:80_000] + "\n...[patch truncated]"
    checks = [record.snapshot() for record in request.records[-20:]]
    return (
        "Perform a read-only independent review. Do not modify files and do not run any "
        "external or publishing action. Assess correctness, regressions, security, and "
        "whether the task is actually satisfied. Return ONLY one JSON object with keys "
        "approved (boolean), summary (string), findings (array of strings), and "
        "blocking_findings (array of strings).\n\n"
        f"TASK:\n{task}\n\nCHECKS:\n{_canonical_json(checks)}\n\nPATCH:\n{patch}"
    )


def _parse_review(text: str) -> ReviewResult:
    decoder = json.JSONDecoder()
    candidates = [index for index, character in enumerate(text) if character == "{"]
    payload: Any = None
    for index in reversed(candidates):
        try:
            payload, _ = decoder.raw_decode(text[index:])
            break
        except json.JSONDecodeError:
            continue
    if not isinstance(payload, dict) or not isinstance(payload.get("approved"), bool):
        return ReviewResult(
            False,
            "Reviewer did not return the required JSON contract",
            blocking_findings=("invalid review response",),
        )
    findings = payload.get("findings") or []
    blocking = payload.get("blocking_findings") or []
    if not isinstance(findings, list) or not isinstance(blocking, list):
        return ReviewResult(
            False,
            "Reviewer returned invalid finding arrays",
            blocking_findings=("invalid review response",),
        )
    approved = bool(payload["approved"]) and not blocking
    return ReviewResult(
        approved,
        _bounded(str(payload.get("summary") or "Independent review"), 2000),
        tuple(_bounded(str(item), 1000) for item in findings[:50]),
        tuple(_bounded(str(item), 1000) for item in blocking[:50]),
    )


def _git_fingerprint(cwd: Path) -> str:
    payload = _git_output(cwd, "status", "--porcelain=v1", "-z")
    payload += _git_output(cwd, "diff", "--binary", "HEAD")
    return hashlib.sha256(payload.encode("utf-8", "surrogateescape")).hexdigest()


def _git_output(cwd: Path, *args: str) -> str:
    import subprocess

    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise CodingLifecycleError("git inspection failed inside coding workspace")
    return completed.stdout.decode("utf-8", "surrogateescape")


def _execution(row: sqlite3.Row) -> CodingExecution:
    return CodingExecution(
        id=str(row["id"]),
        idempotency_key=str(row["idempotency_key"]),
        spec=CodingExecutionSpec.from_payload(json.loads(row["spec_json"])),
        spec_sha256=str(row["spec_sha256"]),
        status=str(row["status"]),  # type: ignore[arg-type]
        version=int(row["version"]),
        workspace_run_id=str(row["workspace_run_id"]),
        active_run_id=str(row["active_run_id"]),
        result=json.loads(row["result_json"]) if row["result_json"] else None,
        error=str(row["error"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        finished_at=str(row["finished_at"]),
    )


def _idempotency_key(value: str) -> str:
    candidate = value.strip()
    if not _KEY_RE.fullmatch(candidate):
        raise ValueError("idempotency_key contains unsupported characters")
    return candidate


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    return str(value)


def _bounded(value: str, maximum: int) -> str:
    return value if len(value) <= maximum else value[: maximum - 1] + "…"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
