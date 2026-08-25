from __future__ import annotations

import hashlib
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kiro_bot.store import Store
from kiro_bot.workspaces import (
    ArtifactError,
    ArtifactLimitExceeded,
    InvalidWorkspaceLease,
    UnsafeCleanupError,
    WorkspaceLease,
    WorkspaceExecutionSpec,
    WorkspaceManager,
    WorkspaceValidationError,
)


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Workspace Test")
    git(repo, "config", "user.email", "workspace@example.test")
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "initial")
    return repo


def make_manager(tmp_path: Path, **limits: int) -> tuple[WorkspaceManager, Path]:
    repo = make_repo(tmp_path)
    manager = WorkspaceManager(Store(tmp_path / "store"), tmp_path / "runs", **limits)
    return manager, repo


def test_create_detached_workspace_and_persist_manifest(tmp_path) -> None:
    manager, repo = make_manager(tmp_path)
    expected_commit = git(repo, "rev-parse", "HEAD")

    lease = manager.create_workspace(repo, "HEAD", "run-001", bot_name="builder")

    assert Path(lease.path).parent == (tmp_path / "runs").resolve()
    assert Path(lease.path).is_dir()
    assert git(Path(lease.path), "rev-parse", "HEAD") == expected_commit
    assert git(Path(lease.path), "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"
    manifest = manager.get_manifest("run-001")
    assert manifest is not None
    assert manifest.state == "active"
    assert manifest.commit == expected_commit
    assert manifest.bot_name == "builder"

    reopened = WorkspaceManager(Store(tmp_path / "store"), tmp_path / "runs")
    persisted = reopened.get_manifest("run-001")
    assert persisted is not None
    assert persisted.worktree_path == lease.path


@pytest.mark.parametrize(
    ("run_id", "ref"),
    [
        ("../escape", "HEAD"),
        ("run;touch-pwned", "HEAD"),
        ("safe-run", "HEAD;touch-pwned"),
        ("safe-run", "--help"),
        ("safe-run", "HEAD@{1}"),
    ],
)
def test_run_and_ref_injection_shapes_are_rejected(tmp_path, run_id, ref) -> None:
    manager, repo = make_manager(tmp_path)
    with pytest.raises(WorkspaceValidationError):
        manager.create_workspace(repo, ref, run_id)


def test_repo_must_be_root_and_disjoint_from_workspace_root(tmp_path) -> None:
    repo = make_repo(tmp_path)
    nested = repo / "nested"
    nested.mkdir()
    manager = WorkspaceManager(Store(tmp_path / "store"), tmp_path / "runs")
    with pytest.raises(WorkspaceValidationError, match="worktree root"):
        manager.create_workspace(nested, "HEAD", "nested-run")

    inside_manager = WorkspaceManager(Store(tmp_path / "other-store"), repo / "runs")
    with pytest.raises(WorkspaceValidationError, match="disjoint"):
        inside_manager.create_workspace(repo, "HEAD", "inside-run")


def test_workspace_root_must_be_narrow_and_not_a_symlink(tmp_path) -> None:
    store = Store(tmp_path / "store")
    with pytest.raises(WorkspaceValidationError, match="too broad"):
        WorkspaceManager(store, Path("/"))
    real_root = tmp_path / "real-runs"
    real_root.mkdir()
    linked_root = tmp_path / "linked-runs"
    linked_root.symlink_to(real_root, target_is_directory=True)
    with pytest.raises(WorkspaceValidationError, match="symlink"):
        WorkspaceManager(store, linked_root)


def test_auto_enumerates_modified_staged_and_untracked_artifacts(tmp_path) -> None:
    manager, repo = make_manager(tmp_path)
    lease = manager.create_workspace(repo, "HEAD", "artifact-run")
    workspace = Path(lease.path)
    (workspace / "README.md").write_text("changed\n", encoding="utf-8")
    (workspace / "report.json").write_text('{"ok":true}\n', encoding="utf-8")
    (workspace / "staged.txt").write_text("staged\n", encoding="utf-8")
    git(workspace, "add", "staged.txt")

    artifacts = manager.enumerate_artifacts(lease)

    assert [item.path for item in artifacts] == ["README.md", "report.json", "staged.txt"]
    report = next(item for item in artifacts if item.path == "report.json")
    assert report.size_bytes == len(b'{"ok":true}\n')
    assert report.sha256 == hashlib.sha256(b'{"ok":true}\n').hexdigest()
    persisted = manager.get_manifest("artifact-run")
    assert persisted is not None
    assert persisted.artifacts == tuple(artifacts)


def test_artifact_containment_symlink_and_size_limits_fail_closed(tmp_path) -> None:
    manager, repo = make_manager(
        tmp_path, max_artifacts=2, max_file_bytes=8, max_total_bytes=12
    )
    lease = manager.create_workspace(repo, "HEAD", "bounded-run")
    workspace = Path(lease.path)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (workspace / "link.txt").symlink_to(outside)

    with pytest.raises(ArtifactError, match="symlink"):
        manager.enumerate_artifacts(lease, ["link.txt"])
    with pytest.raises(ArtifactError, match="normalized relative"):
        manager.enumerate_artifacts(lease, ["../outside.txt"])

    (workspace / "large.bin").write_bytes(b"012345678")
    with pytest.raises(ArtifactLimitExceeded, match="exceeds 8 bytes"):
        manager.enumerate_artifacts(lease, ["large.bin"])
    assert manager.get_manifest("bounded-run").artifacts == ()  # type: ignore[union-attr]


def test_finalize_retains_material_and_cleanup_is_explicit_and_clean_only(tmp_path) -> None:
    manager, repo = make_manager(tmp_path)
    lease = manager.create_workspace(repo, "HEAD", "final-run")
    workspace = Path(lease.path)
    artifact = workspace / "result.txt"
    artifact.write_text("valuable result\n", encoding="utf-8")

    manifest = manager.finalize(lease, "completed")

    assert manifest.state == "completed"
    assert workspace.is_dir()
    assert manifest.artifacts[0].path == "result.txt"
    with pytest.raises(UnsafeCleanupError, match="material changes"):
        manager.cleanup_workspace(lease)
    assert artifact.read_text(encoding="utf-8") == "valuable result\n"

    # The operator explicitly handles the material first. Only then can this
    # module remove the clean, detached, commit-recoverable worktree.
    artifact.unlink()
    cleaned = manager.cleanup_workspace(lease)
    assert cleaned.state == "cleaned"
    assert not workspace.exists()
    assert cleaned.artifacts[0].sha256 == hashlib.sha256(b"valuable result\n").hexdigest()


def test_stale_recovery_invalidates_old_token_without_deleting_workspace(tmp_path) -> None:
    manager, repo = make_manager(tmp_path)
    lease = manager.create_workspace(repo, "HEAD", "stale-run", lease_seconds=1)
    future = datetime.now(timezone.utc) + timedelta(minutes=1)

    stale = manager.recover_stale_leases(now=future)

    assert [item.run_id for item in stale] == ["stale-run"]
    assert stale[0].state == "stale"
    assert Path(lease.path).is_dir()
    with pytest.raises(InvalidWorkspaceLease):
        manager.heartbeat(lease)

    replacement = manager.reacquire_stale("stale-run", lease_seconds=30)
    assert replacement.token != lease.token
    assert manager.heartbeat(replacement, lease_seconds=45).token == replacement.token


def test_forged_lease_cannot_enumerate_finalize_or_cleanup(tmp_path) -> None:
    manager, repo = make_manager(tmp_path)
    lease = manager.create_workspace(repo, "HEAD", "token-run")
    forged = WorkspaceLease(
        run_id=lease.run_id,
        token="wrong-token",
        path=lease.path,
        repo_path=lease.repo_path,
        requested_ref=lease.requested_ref,
        commit=lease.commit,
        lease_expires_at=lease.lease_expires_at,
    )
    for action in (
        lambda: manager.enumerate_artifacts(forged),
        lambda: manager.finalize(forged),
        lambda: manager.cleanup_workspace(forged),
    ):
        with pytest.raises(InvalidWorkspaceLease):
            action()


def test_failed_creation_manifest_and_material_target_are_not_auto_deleted(
    tmp_path, monkeypatch
) -> None:
    manager, repo = make_manager(tmp_path)

    original_run = subprocess.run

    def fail_worktree(argv, **kwargs):
        if "worktree" in argv and "add" in argv:
            target = Path(argv[-2])
            target.mkdir()
            (target / "diagnostic.txt").write_text("retain me", encoding="utf-8")
            return subprocess.CompletedProcess(argv, 1, b"", b"synthetic failure")
        return original_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", fail_worktree)
    with pytest.raises(Exception, match="git command failed"):
        manager.create_workspace(repo, "HEAD", "failed-run")

    manifest = manager.get_manifest("failed-run")
    assert manifest is not None
    assert manifest.state == "failed"
    retained = Path(manifest.worktree_path) / "diagnostic.txt"
    assert retained.read_text(encoding="utf-8") == "retain me"


def test_execution_binding_is_durable_and_can_reuse_a_supplied_lease(tmp_path) -> None:
    manager, repo = make_manager(tmp_path)
    shared = manager.create_workspace(repo, "HEAD", "repair-group", bot_name="builder")

    first = manager.prepare_execution(
        WorkspaceExecutionSpec(
            lease=shared,
            artifact_paths=("README.md",),
            auto_finalize=False,
        ),
        "turn-1",
        bot_name="builder",
    )
    second = manager.prepare_execution(
        WorkspaceExecutionSpec(lease=shared, auto_finalize=False),
        "turn-2",
        bot_name="reviewer",
    )

    reopened = WorkspaceManager(Store(tmp_path / "store"), tmp_path / "runs")
    restored = reopened.resume_execution("turn-1")
    assert restored is not None
    assert restored.lease.token == shared.token
    assert restored.artifact_paths == ("README.md",)
    assert restored.auto_finalize is False
    assert first.lease.path == second.lease.path == shared.path
    assert manager.get_manifest("repair-group").state == "active"  # type: ignore[union-attr]


def test_expired_lease_is_rejected_without_a_recovery_sweep(tmp_path) -> None:
    manager, repo = make_manager(tmp_path)
    lease = manager.create_workspace(repo, "HEAD", "short", lease_seconds=0.01)
    time.sleep(0.03)

    with pytest.raises(InvalidWorkspaceLease, match="expired"):
        manager.validate_lease(lease)
    with pytest.raises(InvalidWorkspaceLease, match="expired"):
        manager.prepare_execution(
            WorkspaceExecutionSpec(lease=lease, auto_finalize=False),
            "turn-after-expiry",
            bot_name="builder",
        )
