from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kyn.store import Store
from kyn.tasks import (
    TaskConflict,
    TaskError,
    TaskStore,
    branch_exists,
    commit_worktree,
    create_task_branch,
    delete_task_branch,
    derive_task_state,
    find_merge_commit,
    merge_marker,
    merge_task_branch,
    push_to_branch,
    remove_worktree,
    resolve_base,
    resolve_commit,
    worktree_diff,
    worktree_is_clean,
)


def _git(repo: Path, *args: str) -> None:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    (repo / "app.py").write_text("x = 1\n")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "init")
    return repo


def test_branch_lifecycle_and_validation(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert resolve_base(str(repo), "HEAD") == "main"
    assert resolve_base(str(repo), "main") == "main"
    with pytest.raises(TaskError):
        resolve_base(str(repo), "nope")
    assert resolve_commit(str(repo), "main")

    create_task_branch(str(repo), "kyn/t1", "main")
    assert branch_exists(str(repo), "kyn/t1")
    with pytest.raises(TaskError):
        create_task_branch(str(repo), "kyn/t1", "main")
    with pytest.raises(TaskError):
        create_task_branch(str(repo), "bad name!", "main")
    with pytest.raises(TaskError):
        create_task_branch(str(repo), "../escape", "main")
    delete_task_branch(str(repo), "kyn/t1")
    assert not branch_exists(str(repo), "kyn/t1")


def test_diff_commit_push_merge_round_trip(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    create_task_branch(str(repo), "kyn/work", "main")
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "--detach", str(wt), "kyn/work")

    (wt / "app.py").write_text("x = 2\n")
    (wt / "new.py").write_text("y = 1\n")
    assert not worktree_is_clean(str(wt))
    diff = worktree_diff(str(wt))
    assert {item["path"] for item in diff.files} == {"app.py", "new.py"}
    assert "x = 2" in diff.diff
    assert not diff.truncated

    assert commit_worktree(str(wt), "kyn task work") is True
    assert commit_worktree(str(wt), "again") is False
    assert worktree_is_clean(str(wt))
    push_to_branch(str(wt), str(repo), "kyn/work")

    result = merge_task_branch(str(repo), "kyn/work", "main", "Merge kyn/work (kyn-task:work)")
    assert result["commit"]
    assert not branch_exists(str(repo), "kyn/work")
    assert (repo / "new.py").read_text() == "y = 1\n"
    assert derive_task_state(str(repo), "kyn/work", "work") == "merged"
    assert find_merge_commit(str(repo), merge_marker("work")) == result["commit"]


def test_merge_conflict_aborts_cleanly(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    create_task_branch(str(repo), "kyn/clash", "main")
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "--detach", str(wt), "kyn/clash")
    (wt / "app.py").write_text("x = 2\n")
    assert commit_worktree(str(wt), "task change") is True
    push_to_branch(str(wt), str(repo), "kyn/clash")
    # Move base the other way on the same line.
    (repo / "app.py").write_text("x = 3\n")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "base moves on")

    with pytest.raises(TaskConflict, match="app.py"):
        merge_task_branch(str(repo), "kyn/clash", "main", "merge it")
    # Aborted: still open, base untouched.
    assert branch_exists(str(repo), "kyn/clash")
    assert (repo / "app.py").read_text() == "x = 3\n"
    assert derive_task_state(str(repo), "kyn/clash", "clash") == "open"


def test_merge_guards_dirty_tree_and_missing_branch(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with pytest.raises(TaskConflict, match="gone"):
        merge_task_branch(str(repo), "kyn/ghost", "main", "merge it")
    create_task_branch(str(repo), "kyn/w", "main")
    (repo / "dirty.py").write_text("z = 0\n")
    with pytest.raises(TaskConflict, match="uncommitted"):
        merge_task_branch(str(repo), "kyn/w", "main", "merge it")


def test_remove_worktree_and_abandon_state(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    create_task_branch(str(repo), "kyn/gone", "main")
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "--detach", str(wt), "kyn/gone")
    (wt / "dirty.py").write_text("z = 0\n")
    remove_worktree(str(wt), force=True)
    assert not wt.exists()
    delete_task_branch(str(repo), "kyn/gone", force=True)
    assert derive_task_state(str(repo), "kyn/gone", "gone") == "abandoned"


def test_task_store_round_trip(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    tasks = TaskStore(store)
    row = tasks.add_task("coding-1", "/repo", "kyn/task-1", "main")
    assert row["branch"] == "kyn/task-1"
    assert tasks.get_task("coding-1") is not None
    assert tasks.get_task("coding-nope") is None
    assert [item["execution_id"] for item in tasks.list_tasks()] == ["coding-1"]
