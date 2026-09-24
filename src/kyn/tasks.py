"""Reviewable coding tasks: branch + isolated work + diff + merge/abandon.

A task wraps one coding execution with a real git branch (``kyn/<execution>``)
so reviewed work can be merged instead of evaporating in a detached worktree:

* create: resolve ``base`` (default: current branch), ``git branch`` it.
  The coding execution then runs detached *at the branch tip*.
* diff: read the execution worktree against HEAD (tracked diff capped,
  untracked files listed, never rendered).
* merge (only for reviewed work — execution ``awaiting_handoff``/``ready``):
  commit the worktree, push ``HEAD:<branch>`` over the loopback path,
  ``--no-ff`` merge into a clean, checked-out ``base``, delete the branch.
* abandon: force-remove the worktree, delete the branch, cancel the run.

Task state is derived, never stored: branch present → open; merge commit
(``kyn-task:<execution>`` marker) present → merged; else abandoned. The only
persisted row maps execution → repo/branch/base.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .store import Store


class TaskError(RuntimeError):
    pass


class TaskConflict(TaskError):
    """Merge/abandon preconditions failed (dirty tree, conflicts, wrong state)."""


_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
_DIFF_CAP_CHARS = 100_000
_GIT_TIMEOUT = 120


def task_branch(execution_id: str) -> str:
    return f"kyn/{execution_id}"


def merge_marker(execution_id: str) -> str:
    return f"kyn-task:{execution_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _git_env() -> dict[str, str]:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    if os.name == "nt" and os.environ.get("SYSTEMROOT"):
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    return env


def _git(repo: str | Path, *args: str, timeout: int = _GIT_TIMEOUT) -> subprocess.CompletedProcess[str]:
    """Run git with hooks disabled (non-interactive host operation)."""
    completed = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        env=_git_env(),
    )
    return completed


def _check(completed: subprocess.CompletedProcess[str], what: str) -> str:
    if completed.returncode != 0:
        detail = (completed.stderr.decode("utf-8", "replace") or completed.stdout.decode("utf-8", "replace")).strip()
        raise TaskError(f"{what} failed: {detail[:500]}" if detail else f"{what} failed")
    return completed.stdout.decode("utf-8", "replace")


def _repo(repo_path: str) -> Path:
    repo = Path(repo_path).expanduser()
    if not repo.is_dir():
        raise TaskError("repository path is not a directory")
    probe = _git(repo, "rev-parse", "--git-dir")
    if probe.returncode != 0:
        raise TaskError("repository path is not a git repository")
    return repo


def _validate_branch_name(branch: str) -> str:
    name = (branch or "").strip()
    if (
        not name
        or not _BRANCH_RE.fullmatch(name)
        or ".." in name
        or name.startswith(("/", "."))
        or name.endswith(("/", ".", ".lock"))
        or "@{" in name
    ):
        raise TaskError(f"invalid branch name {branch!r}")
    return name


def resolve_commit(repo_path: str, ref: str) -> str:
    """Resolve any ref to a commit SHA (pins a moving base)."""
    repo = _repo(repo_path)
    out = _check(_git(repo, "rev-parse", f"{ref}^{{commit}}"), f"resolve {ref!r}")
    sha = out.strip().splitlines()
    if not sha or not sha[0].strip():
        raise TaskError(f"could not resolve {ref!r} to a commit")
    return sha[0].strip()


def resolve_base(repo_path: str, base: str = "HEAD") -> str:
    """Resolve the merge base to a local branch name."""
    repo = _repo(repo_path)
    wanted = (base or "HEAD").strip() or "HEAD"
    if wanted == "HEAD":
        current = _git(repo, "branch", "--show-current")
        if current.returncode != 0 or not current.stdout.decode().strip():
            raise TaskError("HEAD is detached; pass an explicit base branch")
        return current.stdout.decode().strip()
    show = _git(repo, "show-ref", "--verify", f"refs/heads/{wanted}")
    if show.returncode != 0:
        raise TaskError(f"base branch {wanted!r} does not exist")
    return wanted


def create_task_branch(repo_path: str, branch: str, base_commit: str) -> None:
    repo = _repo(repo_path)
    name = _validate_branch_name(branch)
    exists = _git(repo, "show-ref", "--verify", f"refs/heads/{name}")
    if exists.returncode == 0:
        raise TaskError(f"branch {name!r} already exists")
    _check(_git(repo, "branch", name, base_commit), f"create branch {name!r}")


def delete_task_branch(repo_path: str, branch: str, *, force: bool = False) -> None:
    repo = _repo(repo_path)
    name = _validate_branch_name(branch)
    flag = "-D" if force else "-d"
    result = _git(repo, "branch", flag, name)
    if result.returncode != 0 and "not found" not in result.stderr.decode().lower():
        _check(result, f"delete branch {name!r}")


def branch_exists(repo_path: str, branch: str) -> bool:
    try:
        repo = _repo(repo_path)
    except TaskError:
        return False
    name = _validate_branch_name(branch)
    return _git(repo, "show-ref", "--verify", f"refs/heads/{name}").returncode == 0


@dataclass(frozen=True, slots=True)
class WorktreeDiff:
    files: tuple[dict[str, str], ...]
    diff: str
    truncated: bool


def _porcelain_entries(worktree: str | Path) -> list[tuple[str, str]]:
    out = _check(_git(worktree, "status", "--porcelain=v1", "-z", "--untracked-files=all"), "worktree status")
    entries: list[tuple[str, str]] = []
    for record in out.split("\0"):
        if len(record) < 4:
            continue
        entries.append((record[:2].strip() or "??", record[3:]))
    return entries


def worktree_diff(worktree_path: str) -> WorktreeDiff:
    worktree = Path(worktree_path).expanduser()
    if not worktree.is_dir():
        raise TaskError("task worktree is gone")
    entries = _porcelain_entries(worktree)
    files = tuple({"path": path, "status": status} for status, path in entries)
    out = _check(_git(worktree, "diff", "HEAD", "--", "."), "worktree diff")
    truncated = len(out) > _DIFF_CAP_CHARS
    return WorktreeDiff(files=files, diff=out[:_DIFF_CAP_CHARS], truncated=truncated)


def worktree_is_clean(worktree_path: str) -> bool:
    worktree = Path(worktree_path).expanduser()
    if not worktree.is_dir():
        raise TaskError("task worktree is gone")
    return not _porcelain_entries(worktree)


def commit_worktree(worktree_path: str, message: str) -> bool:
    """Commit all worktree changes (tracked + untracked). True if committed."""
    worktree = Path(worktree_path).expanduser()
    if not worktree.is_dir():
        raise TaskError("task worktree is gone")
    if not _porcelain_entries(worktree):
        return False
    _check(_git(worktree, "add", "-A"), "stage task changes")
    _check(
        _git(
            worktree,
            "-c",
            "user.name=Ari",
            "-c",
            "user.email=kyn@local",
            "commit",
            "-m",
            message[:500],
        ),
        "commit task changes",
    )
    return True


def push_to_branch(worktree_path: str, repo_path: str, branch: str) -> None:
    worktree = Path(worktree_path).expanduser()
    if not worktree.is_dir():
        raise TaskError("task worktree is gone")
    name = _validate_branch_name(branch)
    _check(_git(worktree, "push", str(repo_path), f"HEAD:{name}"), f"push to {name!r}")


def merge_task_branch(
    repo_path: str, branch: str, base: str, message: str
) -> dict[str, str]:
    """Merge a task branch into a clean, checked-out base. Returns {commit}."""
    repo = _repo(repo_path)
    name = _validate_branch_name(branch)
    if _git(repo, "show-ref", "--verify", f"refs/heads/{name}").returncode != 0:
        raise TaskConflict(f"branch {name!r} is gone — already merged or abandoned")
    current = _git(repo, "branch", "--show-current")
    if current.stdout.decode().strip() != base:
        raise TaskConflict(
            f"check out {base!r} in {repo} with a clean tree, then merge"
        )
    if _git(repo, "status", "--porcelain").stdout.decode().strip():
        raise TaskConflict(f"{repo} has uncommitted changes — stash or commit first")
    merged = _git(repo, "merge", "--no-ff", "-m", message[:500], name)
    if merged.returncode != 0:
        # Capture the conflict list BEFORE aborting (abort clears it).
        conflicts = _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.decode()
        _git(repo, "merge", "--abort")
        files = sorted({line for line in conflicts.splitlines() if line.strip()})
        raise TaskConflict(
            "merge conflicts in: {}".format(", ".join(files) if files else "unknown files")
        )
    commit = _git(repo, "rev-parse", "HEAD").stdout.decode().strip()
    _check(_git(repo, "branch", "-d", name), f"delete merged branch {name!r}")
    return {"commit": commit}


def remove_worktree(worktree_path: str, *, force: bool = False) -> None:
    worktree = Path(worktree_path).expanduser()
    if not worktree.exists() and not worktree.is_symlink():
        return
    # Worktree removal must run from the *main* repo, not inside the worktree.
    probe = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=_GIT_TIMEOUT,
        check=False,
        env=_git_env(),
    )
    if probe.returncode != 0:
        raise TaskError("task worktree is not a git worktree")
    common = probe.stdout.decode().strip().splitlines()[-1]
    main_repo = str(Path(common).parent) if common.endswith(".git") else common
    args = ["worktree", "remove"] + (["--force"] if force else []) + [str(worktree)]
    _check(_git(main_repo, *args), "remove task worktree")


def find_merge_commit(repo_path: str, marker: str) -> str | None:
    try:
        repo = _repo(repo_path)
    except TaskError:
        return None
    out = _git(repo, "log", "--format=%H", f"--grep={marker}", "--max-count=1")
    if out.returncode != 0:
        return None
    sha = out.stdout.decode().strip().splitlines()
    return sha[0].strip() if sha and sha[0].strip() else None


def derive_task_state(repo_path: str, branch: str, execution_id: str) -> str:
    if branch_exists(repo_path, branch):
        return "open"
    if find_merge_commit(repo_path, merge_marker(execution_id)) is not None:
        return "merged"
    return "abandoned"


class TaskStore:
    """Execution → repo/branch/base mapping for reviewable tasks."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self._migrate()

    def add_task(self, execution_id: str, repo_path: str, branch: str, base: str) -> dict[str, Any]:
        now = _now()
        with self.store.connect() as db:
            db.execute(
                """
                INSERT INTO coding_tasks(execution_id, repo_path, branch, base, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (execution_id, repo_path, branch, base, now),
            )
            row = db.execute(
                "SELECT * FROM coding_tasks WHERE execution_id = ?", (execution_id,)
            ).fetchone()
        assert row is not None
        return dict(row)

    def get_task(self, execution_id: str) -> dict[str, Any] | None:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM coding_tasks WHERE execution_id = ?", (execution_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def list_tasks(self, *, limit: int = 100) -> list[dict[str, Any]]:
        bounded = min(max(int(limit), 1), 500)
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT * FROM coding_tasks ORDER BY created_at DESC, execution_id DESC LIMIT ?",
                (bounded,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _migrate(self) -> None:
        with self.store.connect() as db:
            # No REFERENCES clause on execution_id: coding_executions is owned
            # and migrated by CodingExecutionStore, which may initialize after
            # this store. Orphan rows (execution deleted) are skipped at read
            # time by the task views.
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS coding_tasks (
                    execution_id TEXT PRIMARY KEY,
                    repo_path TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    base TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
