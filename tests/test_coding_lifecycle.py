from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import AsyncIterator

import pytest

from kiro_bot.coding_lifecycle import (
    CheckSpec,
    CodingExecutionConflict,
    CodingExecutionSpec,
    CodingExecutionStore,
    CodingLifecycleController,
)
from kiro_bot.store import Bot, Store
from kiro_bot.workspaces import WorkspaceExecutionSpec, WorkspaceManager


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "KYN Test")
    git(repo, "config", "user.email", "kiro@example.test")
    (repo / "value.txt").write_text("source\n", encoding="utf-8")
    git(repo, "add", "value.txt")
    git(repo, "commit", "-m", "base")
    return repo


class FakeEngine:
    def __init__(self) -> None:
        self.runs: dict[str, dict] = {}
        self.next_id = 1
        self.cancelled: list[str] = []

    async def submit(
        self,
        bot_name: str,
        prompt: str,
        *,
        actor: str,
        execution: WorkspaceExecutionSpec,
    ) -> str:
        assert actor == "coding"
        assert execution.lease is not None
        workspace = Path(execution.lease.path)
        if bot_name == "builder":
            if "Repair the existing candidate" in prompt:
                (workspace / "value.txt").write_text("good\n", encoding="utf-8")
                text = "Repaired the failing candidate."
            else:
                (workspace / "value.txt").write_text("bad\n", encoding="utf-8")
                text = "Implemented the first candidate."
        else:
            assert bot_name == "reviewer"
            assert (workspace / "value.txt").read_text(encoding="utf-8") == "good\n"
            text = (
                '{"approved":true,"summary":"correct and tested",'
                '"findings":[],"blocking_findings":[]}'
            )
        run_id = f"run-{self.next_id}"
        self.next_id += 1
        self.runs[run_id] = {
            "id": run_id,
            "status": "complete",
            "events": [{"kind": "text", "text": text}],
        }
        return run_id

    async def subscribe(self, run_id: str) -> AsyncIterator[dict]:
        assert run_id in self.runs
        if False:
            yield {}

    async def get_run(self, run_id: str) -> dict:
        return self.runs[run_id]

    async def cancel(self, run_id: str) -> None:
        self.cancelled.append(run_id)


async def wait_for_status(
    controller: CodingLifecycleController, execution_id: str, status: str
) -> dict:
    for _ in range(400):
        snapshot = await controller.get(execution_id)
        if snapshot["status"] == status:
            return snapshot
        await asyncio.sleep(0.01)
    raise AssertionError(f"execution did not reach {status}")


def test_issue_to_repair_review_and_human_handoff_is_isolated(tmp_path: Path) -> None:
    async def scenario() -> None:
        repo = make_repo(tmp_path)
        store = Store(tmp_path / "state")
        store.put_bot(Bot("builder", str(repo)))
        store.put_bot(Bot("reviewer", str(repo)))
        manager = WorkspaceManager(store, tmp_path / "workspaces")
        engine = FakeEngine()
        controller = CodingLifecycleController(
            CodingExecutionStore(store), engine, manager
        )
        await controller.start()
        try:
            spec = CodingExecutionSpec(
                repo_path=str(repo),
                task="Change value.txt to good.",
                builder_bot="builder",
                reviewer_bot="reviewer",
                checks=(
                    CheckSpec(
                        "value is good",
                        (
                            sys.executable,
                            "-c",
                            "from pathlib import Path; raise SystemExit(Path('value.txt').read_text() != 'good\\n')",
                        ),
                        10,
                    ),
                ),
                max_repairs=1,
                timeout_seconds=60,
            )
            accepted = await controller.submit(spec, idempotency_key="issue-42")
            handoff = await wait_for_status(
                controller, accepted["id"], "awaiting_handoff"
            )

            assert repo.joinpath("value.txt").read_text(encoding="utf-8") == "source\n"
            manifest = manager.get_manifest(accepted["id"])
            assert manifest is not None and manifest.state == "completed"
            assert Path(manifest.worktree_path, "value.txt").read_text() == "good\n"
            assert handoff["result"]["repair_attempts_used"] == 1
            assert handoff["result"]["review"]["approved"] is True
            assert [item["path"] for item in handoff["result"]["artifact"]["metadata"]["artifacts"]] == ["value.txt"]

            ready = await controller.approve(accepted["id"], handoff["version"])
            assert ready["status"] == "ready"

            duplicate = await controller.submit(spec, idempotency_key="issue-42")
            assert duplicate["id"] == accepted["id"]
            assert len(engine.runs) == 3  # build, repair, independent review
        finally:
            await controller.close()

    asyncio.run(scenario())


def test_idempotency_key_rejects_a_different_spec(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    store = Store(tmp_path / "state")
    ledger = CodingExecutionStore(store)
    first = CodingExecutionSpec(
        str(repo), "first", "builder", "reviewer", (CheckSpec("check", ("true",)),)
    )
    second = CodingExecutionSpec(
        str(repo), "second", "builder", "reviewer", (CheckSpec("check", ("true",)),)
    )
    ledger.create_or_get(first, "same-key")
    with pytest.raises(CodingExecutionConflict, match="different coding specification"):
        ledger.create_or_get(second, "same-key")


def test_stale_handoff_version_cannot_approve(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    store = Store(tmp_path / "state")
    ledger = CodingExecutionStore(store)
    spec = CodingExecutionSpec(
        str(repo), "task", "builder", "reviewer", (CheckSpec("check", ("true",)),)
    )
    execution, _ = ledger.create_or_get(spec, "handoff-version")
    ledger.set_running(execution.id)
    handoff = ledger.finish(execution.id, "awaiting_handoff", result={"ok": True})
    with pytest.raises(CodingExecutionConflict, match="refresh"):
        ledger.approve(execution.id, handoff.version - 1)
