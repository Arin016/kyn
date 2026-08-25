"""Opt-in live smoke for the isolated build/check/review/handoff harness."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from kiro_bot.coding_lifecycle import (
    CheckSpec,
    CodingExecutionSpec,
    CodingExecutionStore,
    CodingLifecycleController,
)
from kiro_bot.engine import Engine, InvalidRunOperation, RunNotFound
from kiro_bot.store import Bot, Store
from kiro_bot.workspaces import WorkspaceManager


def git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=cwd, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="kiro-bot-coding-live-") as root_text:
        root = Path(root_text)
        repo = root / "source"
        repo.mkdir()
        git(repo, "init")
        git(repo, "config", "user.name", "Kiro Bot Live")
        git(repo, "config", "user.email", "kiro-bot@example.test")
        (repo / "SMOKE.txt").write_text("before\n", encoding="utf-8")
        git(repo, "add", "SMOKE.txt")
        git(repo, "commit", "-m", "base")

        store = Store(root / "state")
        store.put_bot(Bot("coding-builder", str(repo)))
        store.put_bot(Bot("coding-reviewer", str(repo)))
        workspaces = WorkspaceManager(store, root / "workspaces")
        engine = Engine(store=store, workspaces=workspaces)
        controller = CodingLifecycleController(
            CodingExecutionStore(store), engine, workspaces
        )
        await engine.start()
        await controller.start()
        try:
            accepted = await controller.submit(
                CodingExecutionSpec(
                    repo_path=str(repo),
                    task=(
                        "Change only SMOKE.txt so its exact contents are KIRO_CODING_OK "
                        "followed by one newline. Do not create any other file."
                    ),
                    builder_bot="coding-builder",
                    reviewer_bot="coding-reviewer",
                    checks=(
                        CheckSpec(
                            "exact smoke value",
                            (
                                sys.executable,
                                "-c",
                                "from pathlib import Path; raise SystemExit(Path('SMOKE.txt').read_text() != 'KIRO_CODING_OK\\n')",
                            ),
                            30,
                        ),
                    ),
                    max_repairs=1,
                    timeout_seconds=600,
                ),
                idempotency_key="live-coding-smoke",
            )
            execution_id = accepted["id"]
            approved_permissions: set[tuple[str, str]] = set()
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                execution = await controller.get(execution_id)
                run_id = execution.get("active_run_id") or ""
                if run_id:
                    try:
                        run = await engine.get_run(run_id)
                    except RunNotFound:
                        run = None
                    if run is not None:
                        for event in run.get("events", []):
                            if event.get("kind") != "permission":
                                continue
                            request_id = str(event.get("request_id") or "")
                            key = (run_id, request_id)
                            if not request_id or key in approved_permissions:
                                continue
                            try:
                                await engine.decide_permission(run_id, request_id, "once")
                            except InvalidRunOperation:
                                pass
                            approved_permissions.add(key)
                if execution["status"] in {
                    "awaiting_handoff", "ready", "failed", "cancelled"
                }:
                    break
                await asyncio.sleep(0.2)
            else:
                raise RuntimeError("live coding execution timed out")

            execution = await controller.get(execution_id)
            if execution["status"] != "awaiting_handoff":
                raise RuntimeError(f"live coding execution failed: {execution!r}")
            if repo.joinpath("SMOKE.txt").read_text(encoding="utf-8") != "before\n":
                raise RuntimeError("source checkout was mutated")
            manifest = workspaces.get_manifest(execution_id)
            if manifest is None or manifest.state != "completed":
                raise RuntimeError(f"workspace was not finalized: {manifest!r}")
            if Path(manifest.worktree_path, "SMOKE.txt").read_text() != "KIRO_CODING_OK\n":
                raise RuntimeError("isolated candidate has the wrong contents")
            ready = await controller.approve(execution_id, execution["version"])
            if ready["status"] != "ready":
                raise RuntimeError(f"handoff approval failed: {ready!r}")
            print("KIRO_CODING_HARNESS_OK")
        finally:
            await controller.close()
            await engine.close()


if __name__ == "__main__":
    asyncio.run(main())
