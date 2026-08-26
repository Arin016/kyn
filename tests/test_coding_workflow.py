from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from kyn.coding_workflow import (
    CancellationToken,
    CodingWorkflow,
    CodingWorkflowCallbacks,
    CodingWorkflowRequest,
    BuildResult,
    CommandResult,
    CommandSpec,
    GateRule,
    ReviewResult,
    RepairResult,
    UnsafeCommandError,
    WorkflowArtifact,
    WorkflowBudget,
    WorkflowPhase,
    WorkspaceRef,
    WorkflowStatus,
)


def run(coro):
    return asyncio.run(coro)


def command(*argv: str) -> CommandSpec:
    return CommandSpec(tuple(argv))


def rule(*argv: str) -> GateRule:
    return GateRule(tuple(argv))


@dataclass
class Calls:
    build: int
    execute: list[tuple[str, ...]]
    repair: int = 0
    review: int = 0
    artifact: int = 0


def test_happy_path_orders_build_gate_review_and_artifact() -> None:
    calls = Calls(0, [])

    async def build(request):
        calls.build += 1
        assert request.workspace.workspace_id == "default"
        return BuildResult("implemented widget", ("src/widget.py",))

    async def execute(spec, _context):
        calls.execute.append(spec.argv)
        return CommandResult(0, stdout="tests passed")

    async def repair(_request):
        raise AssertionError("repair must not run")

    async def review(request):
        calls.review += 1
        assert [item.command.argv for item in request.records] == [("pytest", "-q")]
        return ReviewResult(True, "independent review passed")

    async def artifact(request):
        calls.artifact += 1
        return WorkflowArtifact("reviewed build", ("src/widget.py",), {"attempts": request.repair_attempts_used})

    result = run(CodingWorkflow(CodingWorkflowCallbacks(build, execute, repair, review, artifact)).run(
        CodingWorkflowRequest("run-1", (command("pytest", "-q"),), (rule("pytest"),))
    ))

    assert result.status is WorkflowStatus.COMPLETED
    assert result.phase is WorkflowPhase.COMPLETED
    assert calls.build == 1
    assert calls.execute == [("pytest", "-q")]
    assert calls.review == calls.artifact == 1
    assert result.artifact and result.artifact.files == ("src/widget.py",)
    assert result.snapshot()["artifact"]["metadata"] == {"attempts": 0}


def test_failed_gate_gets_one_bounded_repair_then_independent_review() -> None:
    calls = Calls(0, [])
    order: list[str] = []
    workspace_is_fixed = False

    async def build(request):
        order.append("build")
        assert request.workspace.workspace_id == "shared-workspace"
        return BuildResult("initial implementation")

    async def execute(spec, context):
        calls.execute.append(spec.argv)
        order.append("gates")
        assert context.workspace.workspace_id == "shared-workspace"
        return CommandResult(0 if workspace_is_fixed else 1, stderr="failure")

    async def repair(request):
        nonlocal workspace_is_fixed
        calls.repair += 1
        order.append("repair")
        assert request.attempt == 1
        assert request.workspace.workspace_id == "shared-workspace"
        assert request.failures[0].result and request.failures[0].result.exit_code == 1
        workspace_is_fixed = True
        return RepairResult("fixed failing gate", ("src/widget.py",))

    async def review(request):
        calls.review += 1
        order.append("review")
        assert len(request.records) == 2
        assert request.workspace.root == "/worktree/project"
        return ReviewResult(True, "looks good")

    result = run(CodingWorkflow(CodingWorkflowCallbacks(build, execute, repair, review)).run(
        CodingWorkflowRequest(
            "run-2", (command("pytest", "-q"),), (rule("pytest"),),
            WorkflowBudget(max_repair_attempts=1), workspace=WorkspaceRef("shared-workspace", "/worktree/project"),
        )
    ))

    assert result.status is WorkflowStatus.COMPLETED
    assert result.repair_attempts_used == 1
    assert calls.execute == [("pytest", "-q"), ("pytest", "-q")]
    assert calls.repair == calls.review == 1
    assert order == ["build", "gates", "repair", "gates", "review"]
    assert result.snapshot()["workspace"] == {
        "workspace_id": "shared-workspace", "root": "/worktree/project", "metadata": {}
    }


def test_unsafe_or_ungated_argv_never_reaches_executor() -> None:
    with pytest.raises(UnsafeCommandError, match="shell interpreters"):
        command("bash", "-c", "pytest -q")
    with pytest.raises(UnsafeCommandError, match="publishing"):
        command("git", "push", "origin", "main")
    with pytest.raises(UnsafeCommandError, match="publishing"):
        command("git", "-C", "/worktree/project", "merge", "release")

    seen: list[tuple[str, ...]] = []

    async def build(_request):
        raise AssertionError("invalid argv must prevent any workspace mutation")

    async def execute(spec, _context):
        seen.append(spec.argv)
        return CommandResult(0)

    async def unused_repair(_request):
        return RepairResult("unused")

    async def unused_review(_request):
        return ReviewResult(True, "unused")

    result = run(CodingWorkflow(CodingWorkflowCallbacks(build, execute, unused_repair, unused_review)).run(
        CodingWorkflowRequest("run-3", (command("pytest", "-q"),), (rule("ruff", "check"),))
    ))
    assert result.status is WorkflowStatus.FAILED
    assert "no deterministic argv gate" in result.error
    assert seen == []


def test_cancellation_wins_and_cancels_running_callback() -> None:
    token = CancellationToken()
    observed_cancel = asyncio.Event()

    async def build(_request):
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            observed_cancel.set()
            raise

    async def execute(_spec, _context):
        raise AssertionError("cancelled build must not reach verification gates")

    async def repair(_request):
        return RepairResult("unused")

    async def review(_request):
        return ReviewResult(True, "unused")

    async def scenario():
        workflow = CodingWorkflow(CodingWorkflowCallbacks(build, execute, repair, review))
        task = asyncio.create_task(workflow.run(CodingWorkflowRequest("run-4", (command("pytest"),), (rule("pytest"),), cancellation=token)))
        await asyncio.sleep(0)
        token.cancel("user stopped this run")
        return await task

    result = run(scenario())
    assert result.status is WorkflowStatus.CANCELLED
    assert result.phase is WorkflowPhase.CANCELLED
    assert result.cancellation_reason == "user stopped this run"
    assert observed_cancel.is_set()


def test_output_and_repair_budgets_produce_json_safe_failure() -> None:
    async def build(_request):
        return BuildResult("built")

    async def execute(_spec, _context):
        return CommandResult(1, stdout="x" * 100, stderr="y" * 100)

    async def repair(_request):
        return RepairResult("unused")

    async def review(_request):
        raise AssertionError("review cannot run while gates keep failing")

    result = run(CodingWorkflow(CodingWorkflowCallbacks(build, execute, repair, review)).run(
        CodingWorkflowRequest(
            "run-5", (command("pytest", "first"),), (rule("pytest"),),
            WorkflowBudget(max_repair_attempts=0, max_output_chars_per_command=30, max_total_output_chars=80),
        )
    ))
    snapshot = result.snapshot()
    assert result.status is WorkflowStatus.FAILED
    assert result.phase is WorkflowPhase.GATING
    assert result.records[0].output_truncated
    assert "[output truncated]" in snapshot["records"][0]["result"]["stdout"]
    assert snapshot["review"] is None


def test_blocking_review_reenters_repair_then_reruns_same_gates() -> None:
    order: list[str] = []
    reviewed_once = False

    async def build(_request):
        order.append("build")
        return BuildResult("initial implementation")

    async def execute(spec, _context):
        order.append(f"gate:{spec.argv[-1]}")
        return CommandResult(0)

    async def repair(request):
        order.append(f"repair:{request.cause}")
        assert request.review and request.review.blocking_findings == ("missing edge case",)
        return RepairResult("handled edge case")

    async def review(_request):
        nonlocal reviewed_once
        order.append("review")
        if not reviewed_once:
            reviewed_once = True
            return ReviewResult(False, "changes required", blocking_findings=("missing edge case",))
        return ReviewResult(True, "approved")

    result = run(CodingWorkflow(CodingWorkflowCallbacks(build, execute, repair, review)).run(
        CodingWorkflowRequest("run-6", (command("pytest", "-q"),), (rule("pytest"),), WorkflowBudget(max_repair_attempts=1))
    ))

    assert result.status is WorkflowStatus.COMPLETED
    assert result.repair_attempts_used == 1
    assert order == ["build", "gate:-q", "review", "repair:review", "gate:-q", "review"]
