"""A bounded, callback-driven coding workflow.

This module is deliberately independent of the ACP, Engine, workspace, and
server layers.  An integration supplies four narrow callbacks: execute a
structured command, propose a repair, independently review the result, and
optionally build a final artifact.  The workflow owns ordering, budgets,
cancellation, deterministic command gates, and terminal snapshots.

It accepts argv vectors only.  There is no shell-string execution surface and
publishing/merge operations are rejected before an executor is ever called.
The builder and repairer mutate a caller-owned workspace; argv commands are
only deterministic verification gates over that same workspace.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Awaitable, Callable, Mapping, Sequence


class WorkflowPhase(StrEnum):
    """Observable lifecycle phases, in the order they may be entered."""

    READY = "ready"
    BUILDING = "building"
    EXECUTING = "executing"
    GATING = "gating"
    REPAIRING = "repairing"
    REVIEWING = "reviewing"
    ARTIFACT = "artifact"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowError(RuntimeError):
    """Raised for an invalid workflow definition before a run begins."""


class UnsafeCommandError(WorkflowError):
    """Raised if a command violates the argv-only safety boundary."""


class _RunCancelled(Exception):
    pass


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """One executable command, expressed only as an argv vector.

    ``argv`` must already be tokenized.  A shell interpreter is intentionally
    forbidden: integrations must invoke this directly with an exec-style API.
    """

    argv: tuple[str, ...]
    label: str = ""
    cwd: str | None = None
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        argv = tuple(self.argv)
        if not argv or any(not isinstance(part, str) or not part for part in argv):
            raise UnsafeCommandError("argv must be a non-empty tuple of non-empty strings")
        if any("\x00" in part or "\n" in part or "\r" in part for part in argv):
            raise UnsafeCommandError("argv entries cannot contain control-line characters")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise WorkflowError("command timeout_seconds must be positive")
        _reject_unsafe_argv(argv)

    @property
    def executable(self) -> str:
        return self.argv[0]

    def snapshot(self) -> dict[str, Any]:
        return {
            "argv": list(self.argv),
            "label": self.label,
            "cwd": self.cwd,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True, slots=True)
class CommandResult:
    """The normalized result of one integration-owned argv execution."""

    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    duration_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.exit_code is not None and not isinstance(self.exit_code, int):
            raise WorkflowError("exit_code must be an integer or None")
        if self.duration_seconds < 0:
            raise WorkflowError("duration_seconds cannot be negative")


@dataclass(frozen=True, slots=True)
class GateRule:
    """A deterministic allow rule for a command argv prefix and exit codes."""

    argv_prefix: tuple[str, ...]
    allowed_exit_codes: frozenset[int] = frozenset({0})
    label: str = ""

    def __post_init__(self) -> None:
        if not self.argv_prefix or any(not item for item in self.argv_prefix):
            raise WorkflowError("gate argv_prefix must be non-empty")
        _reject_unsafe_argv(self.argv_prefix)
        if not self.allowed_exit_codes:
            raise WorkflowError("gate must permit at least one exit code")

    def matches(self, command: CommandSpec) -> bool:
        return command.argv[: len(self.argv_prefix)] == self.argv_prefix


@dataclass(frozen=True, slots=True)
class WorkflowBudget:
    max_repair_attempts: int = 2
    max_commands: int = 12
    timeout_seconds: float = 600.0
    max_output_chars_per_command: int = 20_000
    max_total_output_chars: int = 100_000

    def __post_init__(self) -> None:
        if self.max_repair_attempts < 0:
            raise WorkflowError("max_repair_attempts cannot be negative")
        if self.max_commands < 1:
            raise WorkflowError("max_commands must be at least one")
        if self.timeout_seconds <= 0:
            raise WorkflowError("timeout_seconds must be positive")
        if self.max_output_chars_per_command < 1 or self.max_total_output_chars < 1:
            raise WorkflowError("output budgets must be positive")


@dataclass(slots=True)
class CancellationToken:
    """Cooperative cancellation shared with integration callbacks."""

    _event: asyncio.Event = field(default_factory=asyncio.Event)
    reason: str = ""

    def cancel(self, reason: str = "cancelled by caller") -> None:
        self.reason = reason or "cancelled by caller"
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise _RunCancelled(self.reason)


@dataclass(frozen=True, slots=True)
class WorkspaceRef:
    """An opaque, caller-owned workspace reference shared by every callback.

    The workflow neither creates nor closes a workspace.  A host can pass a
    lease ID, a root path, or both, and reuse that same reference across the
    initial execution and every bounded repair turn.
    """

    workspace_id: str
    root: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.workspace_id.strip():
            raise WorkflowError("workspace_id must not be blank")

    def snapshot(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "root": self.root,
            "metadata": _json_safe(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    run_id: str
    workspace: WorkspaceRef
    command_index: int
    repair_attempt: int
    cancellation: CancellationToken
    deadline_monotonic: float


@dataclass(frozen=True, slots=True)
class BuildRequest:
    """The one initial agent-build turn over the caller-owned workspace."""

    run_id: str
    workspace: WorkspaceRef
    cancellation: CancellationToken
    deadline_monotonic: float


@dataclass(frozen=True, slots=True)
class BuildResult:
    """An acknowledgement from a builder; it does not finalize the workspace."""

    summary: str
    changed_files: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    command: CommandSpec
    result: CommandResult
    output_truncated: bool = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "command": self.command.snapshot(),
            "result": {
                "exit_code": self.result.exit_code,
                "stdout": self.result.stdout,
                "stderr": self.result.stderr,
                "timed_out": self.result.timed_out,
                "duration_seconds": self.result.duration_seconds,
            },
            "output_truncated": self.output_truncated,
        }


@dataclass(frozen=True, slots=True)
class GateFailure:
    command: CommandSpec
    reason: str
    result: CommandResult | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "command": self.command.snapshot(),
            "reason": self.reason,
            "exit_code": self.result.exit_code if self.result else None,
        }


@dataclass(frozen=True, slots=True)
class RepairRequest:
    run_id: str
    workspace: WorkspaceRef
    attempt: int
    failures: tuple[GateFailure, ...]
    records: tuple[ExecutionRecord, ...]
    cancellation: CancellationToken
    review: ReviewResult | None = None
    cause: str = "gates"


@dataclass(frozen=True, slots=True)
class RepairResult:
    """An acknowledgement that the repairer attempted a workspace mutation."""

    summary: str
    changed_files: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    """A read-only handoff to a reviewer independent of the repair callback."""

    run_id: str
    workspace: WorkspaceRef
    records: tuple[ExecutionRecord, ...]
    repair_attempts_used: int
    cancellation: CancellationToken


@dataclass(frozen=True, slots=True)
class ReviewResult:
    approved: bool
    summary: str
    findings: tuple[str, ...] = ()
    blocking_findings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkflowArtifact:
    """A terminal, JSON-safe description of the reviewed coding result."""

    summary: str
    files: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        return {"summary": self.summary, "files": list(self.files), "metadata": _json_safe(self.metadata)}


@dataclass(frozen=True, slots=True)
class ArtifactRequest:
    run_id: str
    workspace: WorkspaceRef
    records: tuple[ExecutionRecord, ...]
    review: ReviewResult
    repair_attempts_used: int
    build: BuildResult
    repairs: tuple[RepairResult, ...]


Executor = Callable[[CommandSpec, ExecutionContext], Awaitable[CommandResult]]
Builder = Callable[[BuildRequest], Awaitable[BuildResult]]
Repairer = Callable[[RepairRequest], Awaitable[RepairResult]]
Reviewer = Callable[[ReviewRequest], Awaitable[ReviewResult]]
ArtifactBuilder = Callable[[ArtifactRequest], Awaitable[WorkflowArtifact]]


@dataclass(frozen=True, slots=True)
class CodingWorkflowCallbacks:
    build: Builder
    execute: Executor
    repair: Repairer
    review: Reviewer
    build_artifact: ArtifactBuilder | None = None


@dataclass(frozen=True, slots=True)
class CodingWorkflowRequest:
    run_id: str
    commands: tuple[CommandSpec, ...]
    gate_rules: tuple[GateRule, ...]
    budget: WorkflowBudget = field(default_factory=WorkflowBudget)
    cancellation: CancellationToken = field(default_factory=CancellationToken)
    workspace: WorkspaceRef = field(default_factory=lambda: WorkspaceRef("default"))

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise WorkflowError("run_id must not be blank")
        if not self.commands:
            raise WorkflowError("at least one command is required")
        if not self.gate_rules:
            raise WorkflowError("at least one deterministic gate rule is required")


@dataclass(frozen=True, slots=True)
class CodingWorkflowResult:
    run_id: str
    workspace: WorkspaceRef
    status: WorkflowStatus
    phase: WorkflowPhase
    records: tuple[ExecutionRecord, ...]
    failures: tuple[GateFailure, ...]
    repair_attempts_used: int
    build: BuildResult | None
    repairs: tuple[RepairResult, ...]
    review: ReviewResult | None
    artifact: WorkflowArtifact | None
    error: str = ""
    cancellation_reason: str = ""
    started_at_monotonic: float = 0.0
    finished_at_monotonic: float = 0.0

    def snapshot(self) -> dict[str, Any]:
        """Return a plain JSON-compatible terminal state for any host layer."""

        return {
            "run_id": self.run_id,
            "workspace": self.workspace.snapshot(),
            "status": self.status.value,
            "phase": self.phase.value,
            "records": [record.snapshot() for record in self.records],
            "failures": [failure.snapshot() for failure in self.failures],
            "repair_attempts_used": self.repair_attempts_used,
            "build": None if self.build is None else {
                "summary": self.build.summary, "changed_files": list(self.build.changed_files),
            },
            "repairs": [
                {"summary": repair.summary, "changed_files": list(repair.changed_files)}
                for repair in self.repairs
            ],
            "review": None
            if self.review is None
            else {
                "approved": self.review.approved,
                "summary": self.review.summary,
                "findings": list(self.review.findings),
                "blocking_findings": list(self.review.blocking_findings),
            },
            "artifact": self.artifact.snapshot() if self.artifact else None,
            "error": self.error,
            "cancellation_reason": self.cancellation_reason,
            "duration_seconds": max(0.0, self.finished_at_monotonic - self.started_at_monotonic),
        }


class CodingWorkflow:
    """Run a bounded build → gate → repair → gate → independent-review workflow."""

    def __init__(self, callbacks: CodingWorkflowCallbacks) -> None:
        self._callbacks = callbacks

    async def run(self, request: CodingWorkflowRequest) -> CodingWorkflowResult:
        started = time.monotonic()
        deadline = started + request.budget.timeout_seconds
        records: list[ExecutionRecord] = []
        failures: list[GateFailure] = []
        repairs: list[RepairResult] = []
        build: BuildResult | None = None
        repair_attempts = 0
        phase = WorkflowPhase.READY
        try:
            # Validate the static verification plan before allowing a builder to
            # touch a workspace. Every later verification pass uses this exact
            # same immutable command list, never agent-proposed shell work.
            self._validate_commands(request.commands, request.gate_rules, request.budget, 0)
            request.cancellation.raise_if_cancelled()
            phase = WorkflowPhase.BUILDING
            build = await self._await_callback(
                self._callbacks.build(
                    BuildRequest(request.run_id, request.workspace, request.cancellation, deadline)
                ), request.cancellation, deadline
            )
            if not isinstance(build, BuildResult):
                raise WorkflowError("build callback must return BuildResult")

            review: ReviewResult | None = None
            while True:
                request.cancellation.raise_if_cancelled()
                self._validate_commands(request.commands, request.gate_rules, request.budget, len(records))
                phase = WorkflowPhase.EXECUTING
                batch = await self._execute_batch(
                    request, request.commands, records, repair_attempts, deadline
                )
                records.extend(batch)

                request.cancellation.raise_if_cancelled()
                phase = WorkflowPhase.GATING
                failures = self._gate(batch, request.gate_rules)
                if failures:
                    if repair_attempts >= request.budget.max_repair_attempts:
                        return self._result(
                            request, WorkflowStatus.FAILED, phase, records, failures,
                            repair_attempts, build, repairs, None, None,
                            "deterministic gates failed after the repair budget was exhausted", started,
                        )
                    repair_attempts += 1
                    phase = WorkflowPhase.REPAIRING
                    repair = await self._repair(
                        request, repair_attempts, failures, records, None, "gates", deadline
                    )
                    repairs.append(repair)
                    # Repairs mutate the same workspace, then the exact original
                    # argv gate suite runs again at the top of this loop.
                    continue

                request.cancellation.raise_if_cancelled()
                phase = WorkflowPhase.REVIEWING
                review = await self._await_callback(
                    self._callbacks.review(
                        ReviewRequest(request.run_id, request.workspace, tuple(records), repair_attempts, request.cancellation)
                    ), request.cancellation, deadline
                )
                if not isinstance(review, ReviewResult):
                    raise WorkflowError("review callback must return ReviewResult")
                if review.approved:
                    break
                if not review.blocking_findings:
                    return self._result(
                        request, WorkflowStatus.FAILED, phase, records, failures,
                        repair_attempts, build, repairs, review, None,
                        "independent review did not approve the result", started,
                    )
                if repair_attempts >= request.budget.max_repair_attempts:
                    return self._result(
                        request, WorkflowStatus.FAILED, phase, records, failures,
                        repair_attempts, build, repairs, review, None,
                        "independent review found blocking issues after the repair budget was exhausted", started,
                    )
                repair_attempts += 1
                phase = WorkflowPhase.REPAIRING
                repair = await self._repair(
                    request, repair_attempts, (), records, review, "review", deadline
                )
                repairs.append(repair)

            artifact: WorkflowArtifact | None = None
            if self._callbacks.build_artifact is not None:
                phase = WorkflowPhase.ARTIFACT
                artifact = await self._await_callback(
                    self._callbacks.build_artifact(
                        ArtifactRequest(request.run_id, request.workspace, tuple(records), review, repair_attempts, build, tuple(repairs))
                    ), request.cancellation, deadline
                )
                if not isinstance(artifact, WorkflowArtifact):
                    raise WorkflowError("artifact callback must return WorkflowArtifact")
            return self._result(
                request, WorkflowStatus.COMPLETED, WorkflowPhase.COMPLETED,
                records, (), repair_attempts, build, repairs, review, artifact, "", started,
            )
        except _RunCancelled as exc:
            return self._result(
                request, WorkflowStatus.CANCELLED, WorkflowPhase.CANCELLED,
                records, failures, repair_attempts, build, repairs, None, None, str(exc), started,
                cancellation_reason=request.cancellation.reason or str(exc),
            )
        except TimeoutError:
            return self._result(
                request, WorkflowStatus.FAILED, phase, records, failures, repair_attempts,
                build, repairs, None, None, "workflow timeout budget exhausted", started,
            )
        except Exception as exc:
            return self._result(
                request, WorkflowStatus.FAILED, phase, records, failures, repair_attempts,
                build, repairs, None, None, f"{type(exc).__name__}: {exc}", started,
            )

    async def _repair(
        self,
        request: CodingWorkflowRequest,
        attempt: int,
        failures: Sequence[GateFailure],
        records: Sequence[ExecutionRecord],
        review: ReviewResult | None,
        cause: str,
        deadline: float,
    ) -> RepairResult:
        result = await self._await_callback(
            self._callbacks.repair(
                RepairRequest(
                    request.run_id, request.workspace, attempt, tuple(failures), tuple(records),
                    request.cancellation, review, cause,
                )
            ), request.cancellation, deadline
        )
        if not isinstance(result, RepairResult):
            raise WorkflowError("repair callback must return RepairResult")
        return result

    def _validate_commands(
        self,
        commands: Sequence[CommandSpec],
        gates: Sequence[GateRule],
        budget: WorkflowBudget,
        already_executed: int,
    ) -> None:
        if already_executed + len(commands) > budget.max_commands:
            raise WorkflowError("command budget would be exceeded")
        for command in commands:
            _reject_unsafe_argv(command.argv)
            if not any(rule.matches(command) for rule in gates):
                raise UnsafeCommandError(f"no deterministic argv gate permits {command.executable!r}")

    async def _execute_batch(
        self,
        request: CodingWorkflowRequest,
        commands: Sequence[CommandSpec],
        existing: Sequence[ExecutionRecord],
        repair_attempt: int,
        deadline: float,
    ) -> list[ExecutionRecord]:
        batch: list[ExecutionRecord] = []
        total_output = sum(len(item.result.stdout) + len(item.result.stderr) for item in existing)
        for command in commands:
            request.cancellation.raise_if_cancelled()
            context = ExecutionContext(
                request.run_id, request.workspace, len(existing) + len(batch), repair_attempt,
                request.cancellation, deadline,
            )
            callback_timeout = _remaining_timeout(deadline, command.timeout_seconds)
            result = await self._await_callback(
                self._callbacks.execute(command, context), request.cancellation, deadline, callback_timeout
            )
            if not isinstance(result, CommandResult):
                raise WorkflowError("execute callback must return CommandResult")
            normalized, truncated = _cap_result(result, request.budget.max_output_chars_per_command)
            total_output += len(normalized.stdout) + len(normalized.stderr)
            if total_output > request.budget.max_total_output_chars:
                raise WorkflowError("total output budget exceeded")
            batch.append(ExecutionRecord(command, normalized, truncated))
        return batch

    def _gate(self, records: Sequence[ExecutionRecord], rules: Sequence[GateRule]) -> list[GateFailure]:
        failures: list[GateFailure] = []
        for record in records:
            matching = [rule for rule in rules if rule.matches(record.command)]
            if not matching:
                failures.append(GateFailure(record.command, "no deterministic gate matched", record.result))
                continue
            permitted = set().union(*(rule.allowed_exit_codes for rule in matching))
            if record.result.timed_out:
                failures.append(GateFailure(record.command, "command timed out", record.result))
            elif record.result.exit_code not in permitted:
                failures.append(
                    GateFailure(record.command, f"exit code {record.result.exit_code!r} is not permitted", record.result)
                )
        return failures

    async def _await_callback(
        self,
        value: Awaitable[Any],
        cancellation: CancellationToken,
        deadline: float,
        cap_seconds: float | None = None,
    ) -> Any:
        if not inspect.isawaitable(value):
            raise WorkflowError("workflow callbacks must be async")
        remaining = _remaining_timeout(deadline, cap_seconds)
        callback_task = asyncio.ensure_future(value)
        cancel_task = asyncio.create_task(cancellation.wait())
        try:
            done, _pending = await asyncio.wait(
                {callback_task, cancel_task}, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
            )
            if not done:
                callback_task.cancel()
                await asyncio.gather(callback_task, return_exceptions=True)
                raise TimeoutError
            if cancel_task in done:
                callback_task.cancel()
                await asyncio.gather(callback_task, return_exceptions=True)
                raise _RunCancelled(cancellation.reason or "cancelled by caller")
            return await callback_task
        finally:
            cancel_task.cancel()
            await asyncio.gather(cancel_task, return_exceptions=True)

    def _result(
        self,
        request: CodingWorkflowRequest,
        status: WorkflowStatus,
        phase: WorkflowPhase,
        records: Sequence[ExecutionRecord],
        failures: Sequence[GateFailure],
        repair_attempts: int,
        build: BuildResult | None,
        repairs: Sequence[RepairResult],
        review: ReviewResult | None,
        artifact: WorkflowArtifact | None,
        error: str,
        started: float,
        *,
        cancellation_reason: str = "",
    ) -> CodingWorkflowResult:
        return CodingWorkflowResult(
            request.run_id, request.workspace, status, phase, tuple(records), tuple(failures), repair_attempts,
            build, tuple(repairs), review, artifact, error, cancellation_reason, started, time.monotonic(),
        )


_SHELLS = frozenset({"sh", "bash", "zsh", "fish", "dash", "cmd", "cmd.exe", "powershell", "pwsh"})
def _reject_unsafe_argv(argv: Sequence[str]) -> None:
    executable = argv[0].rsplit("/", 1)[-1].lower()
    if executable in _SHELLS:
        raise UnsafeCommandError("shell interpreters are not permitted; use a tokenized direct argv command")
    arguments = tuple(item.lower() for item in argv[1:])
    disallowed = (
        executable == "git" and any(item in {"push", "merge", "rebase"} for item in arguments)
    ) or (
        executable == "gh" and "pr" in arguments
    ) or (
        executable in {"npm", "pnpm", "yarn", "cargo"} and "publish" in arguments
    ) or (
        executable == "twine" and "upload" in arguments
    )
    if disallowed:
        raise UnsafeCommandError("publishing, merge, rebase, and push commands are outside this workflow")


def _remaining_timeout(deadline: float, cap_seconds: float | None = None) -> float:
    remaining = deadline - time.monotonic()
    if cap_seconds is not None:
        remaining = min(remaining, cap_seconds)
    if remaining <= 0:
        raise TimeoutError
    return remaining


def _cap_result(result: CommandResult, cap: int) -> tuple[CommandResult, bool]:
    stdout, stdout_cut = _truncate(result.stdout, cap)
    stderr, stderr_cut = _truncate(result.stderr, cap)
    return (
        CommandResult(result.exit_code, stdout, stderr, result.timed_out, result.duration_seconds),
        stdout_cut or stderr_cut,
    )


def _truncate(value: str, cap: int) -> tuple[str, bool]:
    if len(value) <= cap:
        return value, False
    marker = "\n…[output truncated]"
    return value[: max(0, cap - len(marker))] + marker, True


def _json_safe(value: Any) -> Any:
    """Normalize arbitrary artifact metadata without leaking custom objects."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(value[key]) for key in sorted(value, key=lambda item: str(item))}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_safe(item) for item in sorted(value, key=repr)]
    return str(value)
