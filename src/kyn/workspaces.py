"""Isolated git worktrees and bounded artifact manifests for bot runs.

Worktrees are intentionally retained after a run.  The only removal operation
is an explicit, token-authenticated cleanup of a finalized *clean* worktree;
dirty or otherwise material workspaces are never removed by this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import stat
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Literal, Sequence

from .store import Store


WorkspaceState = Literal[
    "creating", "active", "completed", "failed", "cancelled", "stale", "cleaned"
]
FinalOutcome = Literal["completed", "failed", "cancelled"]

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_BOT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+~-]{0,127}$")
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@+~^-]{0,255}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_FINAL_STATES = frozenset({"completed", "failed", "cancelled"})
_ALL_STATES = frozenset(
    {"creating", "active", "completed", "failed", "cancelled", "stale", "cleaned"}
)
_DEFAULT_MAX_ARTIFACTS = 128
_DEFAULT_MAX_FILE_BYTES = 25 * 1024 * 1024
_DEFAULT_MAX_TOTAL_BYTES = 100 * 1024 * 1024


class WorkspaceError(RuntimeError):
    pass


class WorkspaceValidationError(WorkspaceError, ValueError):
    pass


class WorkspaceConflictError(WorkspaceError):
    pass


class InvalidWorkspaceLease(WorkspaceError):
    pass


class GitWorkspaceError(WorkspaceError):
    pass


class ArtifactError(WorkspaceError):
    pass


class ArtifactLimitExceeded(ArtifactError):
    pass


class UnsafeCleanupError(WorkspaceError):
    pass


@dataclass(frozen=True, slots=True)
class Artifact:
    run_id: str
    path: str
    size_bytes: int
    sha256: str
    modified_at: str
    discovered_at: str

    def summary(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "modified_at": self.modified_at,
            "discovered_at": self.discovered_at,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceLease:
    run_id: str
    token: str
    path: str
    repo_path: str
    requested_ref: str
    commit: str
    lease_expires_at: str


@dataclass(frozen=True, slots=True)
class WorkspaceExecutionSpec:
    """Opt-in execution contract for one engine run.

    ``lease`` lets a higher-level harness reuse a worktree across several Kiro
    turns. When it is omitted, ``repo_path`` is required and the manager creates
    a worktree owned by the new run.
    """

    repo_path: str = ""
    ref: str = "HEAD"
    lease_seconds: float = 3600
    artifact_paths: tuple[str, ...] | None = None
    auto_finalize: bool = True
    lease: WorkspaceLease | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class WorkspaceExecution:
    lease: WorkspaceLease
    artifact_paths: tuple[str, ...] | None
    auto_finalize: bool
    lease_seconds: float
    workspace_state: WorkspaceState = "active"

    def summary(self) -> dict[str, Any]:
        return {
            "workspace_run_id": self.lease.run_id,
            "path": self.lease.path,
            "repo_path": self.lease.repo_path,
            "requested_ref": self.lease.requested_ref,
            "commit": self.lease.commit,
            "lease_expires_at": self.lease.lease_expires_at,
            "artifact_paths": list(self.artifact_paths) if self.artifact_paths else None,
            "auto_finalize": self.auto_finalize,
            "lease_seconds": self.lease_seconds,
            "state": self.workspace_state,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceManifest:
    run_id: str
    bot_name: str
    repo_path: str
    requested_ref: str
    commit: str
    worktree_path: str
    state: WorkspaceState
    created_at: str
    updated_at: str
    lease_expires_at: str
    finalized_at: str = ""
    error: str = ""
    artifacts: tuple[Artifact, ...] = field(default_factory=tuple)

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "bot_name": self.bot_name,
            "repo_path": self.repo_path,
            "requested_ref": self.requested_ref,
            "commit": self.commit,
            "worktree_path": self.worktree_path,
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "lease_expires_at": self.lease_expires_at,
            "finalized_at": self.finalized_at,
            "error": self.error,
            "artifacts": [artifact.summary() for artifact in self.artifacts],
        }


class WorkspaceManager:
    """Create and track one detached git worktree per run."""

    def __init__(
        self,
        store: Store,
        root: str | Path,
        *,
        max_artifacts: int = _DEFAULT_MAX_ARTIFACTS,
        max_file_bytes: int = _DEFAULT_MAX_FILE_BYTES,
        max_total_bytes: int = _DEFAULT_MAX_TOTAL_BYTES,
    ) -> None:
        self.store = store
        self.root = _prepare_narrow_root(root)
        self.max_artifacts = _positive_limit(max_artifacts, "max_artifacts", 10_000)
        self.max_file_bytes = _positive_limit(
            max_file_bytes, "max_file_bytes", 10 * 1024 * 1024 * 1024
        )
        self.max_total_bytes = _positive_limit(
            max_total_bytes, "max_total_bytes", 50 * 1024 * 1024 * 1024
        )
        if self.max_file_bytes > self.max_total_bytes:
            raise WorkspaceValidationError("max_file_bytes cannot exceed max_total_bytes")
        self._migrate()

    def prepare_execution(
        self,
        spec: WorkspaceExecutionSpec,
        run_id: str,
        *,
        bot_name: str,
    ) -> WorkspaceExecution:
        """Create or bind a durable execution workspace for an engine run."""
        if not isinstance(spec, WorkspaceExecutionSpec):
            raise WorkspaceValidationError("execution must be a WorkspaceExecutionSpec")
        run = _validate_run_id(run_id)
        bot = _validate_bot_name(bot_name)
        if not isinstance(spec.auto_finalize, bool):
            raise WorkspaceValidationError("auto_finalize must be a boolean")
        _lease_delta(spec.lease_seconds)
        artifact_paths = (
            tuple(dict.fromkeys(_normalize_artifact_path(path) for path in spec.artifact_paths))
            if spec.artifact_paths is not None
            else None
        )
        if artifact_paths is not None and len(artifact_paths) > self.max_artifacts:
            raise ArtifactLimitExceeded(
                f"artifact count exceeds configured limit of {self.max_artifacts}"
            )

        if spec.lease is None:
            if not spec.repo_path:
                raise WorkspaceValidationError(
                    "repo_path is required when no existing workspace lease is supplied"
                )
            lease = self.create_workspace(
                spec.repo_path,
                spec.ref,
                run,
                bot_name=bot,
                lease_seconds=spec.lease_seconds,
            )
        else:
            lease = self.validate_lease(spec.lease)

        timestamp = _iso(_utc_now())
        payload = json.dumps(list(artifact_paths) if artifact_paths is not None else None)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM workspace_execution_bindings WHERE run_id = ?", (run,)
            ).fetchone()
            immutable = (
                lease.run_id,
                bot,
                int(spec.auto_finalize),
                payload,
                float(spec.lease_seconds),
            )
            if existing is None:
                db.execute(
                    """
                    INSERT INTO workspace_execution_bindings(
                        run_id, workspace_run_id, bot_name, auto_finalize,
                        artifact_paths_json, lease_seconds, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (run, *immutable, timestamp),
                )
            elif (
                existing["workspace_run_id"],
                existing["bot_name"],
                int(existing["auto_finalize"]),
                existing["artifact_paths_json"],
                float(existing["lease_seconds"]),
            ) != immutable:
                raise WorkspaceConflictError(
                    f"execution workspace binding for run {run!r} already differs"
                )
        return WorkspaceExecution(
            lease,
            artifact_paths,
            spec.auto_finalize,
            float(spec.lease_seconds),
            "active",
        )

    def resume_execution(self, run_id: str) -> WorkspaceExecution | None:
        """Restore the trusted lease for an engine-owned durable binding."""
        run = _validate_run_id(run_id)
        with self.store.connect() as db:
            binding = db.execute(
                "SELECT * FROM workspace_execution_bindings WHERE run_id = ?", (run,)
            ).fetchone()
            if binding is None:
                return None
            row = db.execute(
                "SELECT * FROM workspace_manifests WHERE run_id = ?",
                (binding["workspace_run_id"],),
            ).fetchone()
            if row is None:
                raise InvalidWorkspaceLease("bound workspace manifest is missing")
            lease = _lease_from_row(row)
            state = str(row["state"])
            if state == "active":
                self._require_lease_row(db, lease, states={"active"})
            elif state not in _FINAL_STATES:
                raise InvalidWorkspaceLease(
                    f"bound workspace state {state!r} cannot be resumed"
                )
            self._validated_lease_path(row)
        raw_paths = json.loads(binding["artifact_paths_json"])
        paths = tuple(str(path) for path in raw_paths) if raw_paths is not None else None
        return WorkspaceExecution(
            lease,
            paths,
            bool(binding["auto_finalize"]),
            float(binding["lease_seconds"]),
            state,  # type: ignore[arg-type]
        )

    def validate_lease(self, lease: WorkspaceLease) -> WorkspaceLease:
        """Validate identity, expiry and containment without extending a lease."""
        with self.store.connect() as db:
            row = self._require_lease_row(db, lease, states={"active"})
            self._validated_lease_path(row)
        return _lease_from_row(row)

    def create_workspace(
        self,
        repo_path: str | Path,
        ref: str,
        run_id: str,
        *,
        bot_name: str = "",
        lease_seconds: float = 3600,
    ) -> WorkspaceLease:
        """Reserve a run and create a detached worktree at its resolved commit."""
        run = _validate_run_id(run_id)
        bot = _validate_bot_name(bot_name)
        requested_ref = _validate_ref(ref)
        lease_delta = _lease_delta(lease_seconds)
        repo = self._validate_repo(repo_path)
        self._require_disjoint_root(repo)
        commit = self._resolve_commit(repo, requested_ref)
        destination = (self.root / run).resolve(strict=False)
        _require_contained(self.root, destination)
        now = _utc_now()
        timestamp = _iso(now)
        expires = _iso(now + lease_delta)
        token = secrets.token_urlsafe(24)

        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM workspace_manifests WHERE run_id = ?", (run,)
            ).fetchone()
            if existing is not None:
                if (
                    existing["state"] == "active"
                    and existing["repo_path"] == str(repo)
                    and existing["commit_hash"] == commit
                    and Path(existing["worktree_path"]).is_dir()
                ):
                    return _lease_from_row(existing)
                raise WorkspaceConflictError(f"workspace run {run!r} already exists")
            if destination.exists() or destination.is_symlink():
                raise WorkspaceConflictError(f"workspace path already exists: {destination}")
            db.execute(
                """
                INSERT INTO workspace_manifests(
                    run_id, bot_name, repo_path, requested_ref, commit_hash,
                    worktree_path, lease_token, state, created_at, updated_at,
                    lease_expires_at, finalized_at, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'creating', ?, ?, ?, '', '')
                """,
                (
                    run,
                    bot,
                    str(repo),
                    requested_ref,
                    commit,
                    str(destination),
                    token,
                    timestamp,
                    timestamp,
                    expires,
                ),
            )

        try:
            _git(
                repo,
                ["worktree", "add", "--detach", str(destination), commit],
                timeout=120,
            )
            actual_commit = _git(destination, ["rev-parse", "HEAD"]).strip()
            if actual_commit != commit:
                raise GitWorkspaceError("created worktree does not match its resolved commit")
        except Exception as exc:
            # A failed git invocation may have created a material partial
            # directory. Persist and retain it; never clean it implicitly.
            with self.store.connect() as db:
                db.execute(
                    """
                    UPDATE workspace_manifests
                    SET state = 'failed', error = ?, updated_at = ?, finalized_at = ?
                    WHERE run_id = ? AND lease_token = ? AND state = 'creating'
                    """,
                    (_safe_error(exc), timestamp, timestamp, run, token),
                )
            if isinstance(exc, WorkspaceError):
                raise
            raise GitWorkspaceError(f"could not create worktree for run {run!r}") from exc

        with self.store.connect() as db:
            cursor = db.execute(
                """
                UPDATE workspace_manifests
                SET state = 'active', updated_at = ?
                WHERE run_id = ? AND lease_token = ? AND state = 'creating'
                """,
                (timestamp, run, token),
            )
            if cursor.rowcount != 1:
                raise InvalidWorkspaceLease("workspace reservation changed during creation")
        return WorkspaceLease(
            run_id=run,
            token=token,
            path=str(destination),
            repo_path=str(repo),
            requested_ref=requested_ref,
            commit=commit,
            lease_expires_at=expires,
        )

    def get_manifest(self, run_id: str) -> WorkspaceManifest | None:
        run = _validate_run_id(run_id)
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM workspace_manifests WHERE run_id = ?", (run,)
            ).fetchone()
            if row is None:
                return None
            artifacts = db.execute(
                "SELECT * FROM workspace_artifacts WHERE run_id = ? ORDER BY path", (run,)
            ).fetchall()
        return _manifest_from_rows(row, artifacts)

    def list_manifests(
        self, *, states: Sequence[WorkspaceState] | None = None
    ) -> list[WorkspaceManifest]:
        normalized: tuple[str, ...] = ()
        if states is not None:
            normalized = tuple(dict.fromkeys(states))
            if not normalized or any(state not in _ALL_STATES for state in normalized):
                raise WorkspaceValidationError("states contains an invalid workspace state")
        query = "SELECT run_id FROM workspace_manifests"
        params: tuple[Any, ...] = ()
        if normalized:
            query += f" WHERE state IN ({','.join('?' for _ in normalized)})"
            params = normalized
        query += " ORDER BY created_at, run_id"
        with self.store.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [manifest for row in rows if (manifest := self.get_manifest(row["run_id"]))]

    def heartbeat(
        self, lease: WorkspaceLease, *, lease_seconds: float = 3600
    ) -> WorkspaceLease:
        now = _utc_now()
        expires = _iso(now + _lease_delta(lease_seconds))
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._require_lease_row(db, lease, states={"active"})
            db.execute(
                """
                UPDATE workspace_manifests
                SET lease_expires_at = ?, updated_at = ? WHERE run_id = ?
                """,
                (expires, _iso(now), lease.run_id),
            )
        return WorkspaceLease(
            run_id=lease.run_id,
            token=lease.token,
            path=str(row["worktree_path"]),
            repo_path=str(row["repo_path"]),
            requested_ref=str(row["requested_ref"]),
            commit=str(row["commit_hash"]),
            lease_expires_at=expires,
        )

    def enumerate_artifacts(
        self,
        lease: WorkspaceLease,
        paths: Sequence[str | Path] | None = None,
    ) -> list[Artifact]:
        """Hash and persist bounded material files contained by the worktree."""
        with self.store.connect() as db:
            row = self._require_lease_row(db, lease, states={"active"})
        workspace = self._validated_lease_path(row)
        requested_paths = (
            self._discover_changed_paths(workspace)
            if paths is None
            else [_normalize_artifact_path(path) for path in paths]
        )
        unique_paths = sorted(dict.fromkeys(requested_paths))
        if len(unique_paths) > self.max_artifacts:
            raise ArtifactLimitExceeded(
                f"artifact count exceeds configured limit of {self.max_artifacts}"
            )

        discovered_at = _iso(_utc_now())
        artifacts: list[Artifact] = []
        total = 0
        for relative in unique_paths:
            artifact = self._hash_artifact(workspace, lease.run_id, relative, discovered_at)
            total += artifact.size_bytes
            if total > self.max_total_bytes:
                raise ArtifactLimitExceeded(
                    f"artifact total exceeds configured limit of {self.max_total_bytes} bytes"
                )
            artifacts.append(artifact)

        # Replace atomically only after every path and limit has passed. A
        # concurrent finalizer or stale recovery invalidates this write.
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_lease_row(db, lease, states={"active"})
            db.execute("DELETE FROM workspace_artifacts WHERE run_id = ?", (lease.run_id,))
            db.executemany(
                """
                INSERT INTO workspace_artifacts(
                    run_id, path, size_bytes, sha256, modified_at, discovered_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.run_id,
                        item.path,
                        item.size_bytes,
                        item.sha256,
                        item.modified_at,
                        item.discovered_at,
                    )
                    for item in artifacts
                ],
            )
            db.execute(
                "UPDATE workspace_manifests SET updated_at = ? WHERE run_id = ?",
                (discovered_at, lease.run_id),
            )
        return artifacts

    def finalize(
        self,
        lease: WorkspaceLease,
        outcome: FinalOutcome = "completed",
        *,
        artifact_paths: Sequence[str | Path] | None = None,
    ) -> WorkspaceManifest:
        if outcome not in _FINAL_STATES:
            raise WorkspaceValidationError("outcome must be completed, failed, or cancelled")
        existing = self.get_manifest(lease.run_id)
        if existing is not None and existing.state in _FINAL_STATES:
            with self.store.connect() as db:
                self._require_lease_row(
                    db, lease, states=set(_FINAL_STATES), check_expiry=False
                )
            if existing.state != outcome:
                raise InvalidWorkspaceLease(
                    f"workspace is already finalized as {existing.state!r}"
                )
            return existing
        self.enumerate_artifacts(lease, artifact_paths)
        timestamp = _iso(_utc_now())
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_lease_row(db, lease, states={"active"})
            db.execute(
                """
                UPDATE workspace_manifests
                SET state = ?, finalized_at = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (outcome, timestamp, timestamp, lease.run_id),
            )
        manifest = self.get_manifest(lease.run_id)
        assert manifest is not None
        return manifest

    def finalize_failure(
        self,
        lease: WorkspaceLease,
        error: BaseException | str,
    ) -> WorkspaceManifest:
        """Fail-close an execution manifest when artifact finalization fails.

        Expiry cannot grant further execution, but the holder of the exact
        persisted token may still seal the retained workspace as failed.
        """
        timestamp = _iso(_utc_now())
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._require_lease_row(
                db, lease, states={"active"}, check_expiry=False
            )
            self._validated_lease_path(row)
            db.execute(
                """
                UPDATE workspace_manifests
                SET state = 'failed', finalized_at = ?, updated_at = ?, error = ?
                WHERE run_id = ? AND state = 'active'
                """,
                (timestamp, timestamp, _safe_error_text(error), lease.run_id),
            )
        manifest = self.get_manifest(lease.run_id)
        assert manifest is not None
        return manifest

    def recover_stale_leases(
        self, *, now: datetime | None = None
    ) -> list[WorkspaceManifest]:
        """Invalidate expired leases without touching retained worktree paths."""
        timestamp = _iso(_coerce_utc(now))
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                """
                SELECT run_id FROM workspace_manifests
                WHERE state IN ('creating', 'active') AND lease_expires_at <= ?
                ORDER BY run_id
                """,
                (timestamp,),
            ).fetchall()
            run_ids = [str(row["run_id"]) for row in rows]
            if run_ids:
                db.execute(
                    f"""
                    UPDATE workspace_manifests
                    SET state = 'stale', lease_token = '', updated_at = ?,
                        error = CASE WHEN error = '' THEN 'lease_expired' ELSE error END
                    WHERE run_id IN ({','.join('?' for _ in run_ids)})
                    """,
                    (timestamp, *run_ids),
                )
        return [manifest for run_id in run_ids if (manifest := self.get_manifest(run_id))]

    def reacquire_stale(
        self, run_id: str, *, lease_seconds: float = 3600
    ) -> WorkspaceLease:
        run = _validate_run_id(run_id)
        now = _utc_now()
        expires = _iso(now + _lease_delta(lease_seconds))
        token = secrets.token_urlsafe(24)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM workspace_manifests WHERE run_id = ?", (run,)
            ).fetchone()
            if row is None or row["state"] != "stale":
                raise InvalidWorkspaceLease("only a stale workspace can be reacquired")
            path = self._validated_lease_path(row)
            top = Path(_git(path, ["rev-parse", "--show-toplevel"]).strip()).resolve()
            if top != path:
                raise InvalidWorkspaceLease("retained path is not the expected git worktree")
            actual_commit = _git(path, ["rev-parse", "HEAD"]).strip()
            if actual_commit != row["commit_hash"]:
                raise InvalidWorkspaceLease("retained worktree commit identity changed")
            db.execute(
                """
                UPDATE workspace_manifests
                SET state = 'active', lease_token = ?, lease_expires_at = ?,
                    updated_at = ?, error = '' WHERE run_id = ? AND state = 'stale'
                """,
                (token, expires, _iso(now), run),
            )
        return WorkspaceLease(
            run_id=run,
            token=token,
            path=str(path),
            repo_path=str(row["repo_path"]),
            requested_ref=str(row["requested_ref"]),
            commit=str(row["commit_hash"]),
            lease_expires_at=expires,
        )

    def cleanup_workspace(self, lease: WorkspaceLease) -> WorkspaceManifest:
        """Explicitly remove a finalized clean worktree, never material changes."""
        with self.store.connect() as db:
            row = self._require_lease_row(db, lease, states=set(_FINAL_STATES))
        path = self._validated_lease_path(row)
        status_text = _git(path, ["status", "--porcelain=v1", "--untracked-files=all"])
        if status_text:
            raise UnsafeCleanupError("worktree contains material changes and will be retained")
        repo = Path(row["repo_path"]).resolve()
        self._require_disjoint_root(repo)
        # No --force: git is the final guard against deleting a changed or
        # administratively locked worktree. A clean detached tree is recoverable
        # from the persisted commit hash.
        _git(repo, ["worktree", "remove", str(path)], timeout=120)
        timestamp = _iso(_utc_now())
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_lease_row(db, lease, states=set(_FINAL_STATES))
            db.execute(
                """
                UPDATE workspace_manifests SET state = 'cleaned', updated_at = ?
                WHERE run_id = ?
                """,
                (timestamp, lease.run_id),
            )
        manifest = self.get_manifest(lease.run_id)
        assert manifest is not None
        return manifest

    def _validate_repo(self, value: str | Path) -> Path:
        if not isinstance(value, (str, Path)) or _CONTROL_RE.search(str(value)):
            raise WorkspaceValidationError("repository path is invalid")
        repo = Path(value).expanduser().resolve()
        if not repo.is_dir():
            raise WorkspaceValidationError("repository path must be an existing directory")
        try:
            inside = _git(repo, ["rev-parse", "--is-inside-work-tree"]).strip()
            top = Path(_git(repo, ["rev-parse", "--show-toplevel"]).strip()).resolve()
        except GitWorkspaceError as exc:
            raise WorkspaceValidationError("repository path is not a git worktree") from exc
        if inside != "true" or top != repo:
            raise WorkspaceValidationError("repository path must be the git worktree root")
        return repo

    def _require_disjoint_root(self, repo: Path) -> None:
        if _contains(repo, self.root) or _contains(self.root, repo):
            raise WorkspaceValidationError(
                "workspace root and source repository must be disjoint directories"
            )

    @staticmethod
    def _resolve_commit(repo: Path, ref: str) -> str:
        try:
            commit = _git(repo, ["rev-parse", "--verify", f"{ref}^{{commit}}"]).strip()
        except GitWorkspaceError as exc:
            raise WorkspaceValidationError(f"ref {ref!r} does not resolve to a commit") from exc
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
            raise WorkspaceValidationError("git returned an invalid commit identifier")
        return commit.lower()

    def _require_lease_row(
        self,
        db: sqlite3.Connection,
        lease: WorkspaceLease,
        *,
        states: set[str],
        check_expiry: bool = True,
    ) -> sqlite3.Row:
        if not isinstance(lease, WorkspaceLease):
            raise InvalidWorkspaceLease("a WorkspaceLease is required")
        row = db.execute(
            "SELECT * FROM workspace_manifests WHERE run_id = ?", (lease.run_id,)
        ).fetchone()
        if row is None or not row["lease_token"] or not secrets.compare_digest(
            str(row["lease_token"]), lease.token
        ):
            raise InvalidWorkspaceLease("workspace lease token is invalid")
        if row["state"] not in states:
            raise InvalidWorkspaceLease(
                f"workspace state {row['state']!r} does not permit this operation"
            )
        if (
            row["worktree_path"] != lease.path
            or row["repo_path"] != lease.repo_path
            or row["commit_hash"] != lease.commit
        ):
            raise InvalidWorkspaceLease("workspace lease identity does not match its manifest")
        if check_expiry and row["state"] in {"creating", "active"}:
            try:
                expires = datetime.fromisoformat(str(row["lease_expires_at"]))
            except ValueError as exc:
                raise InvalidWorkspaceLease("workspace lease expiry is invalid") from exc
            if _coerce_utc(expires) <= _utc_now():
                raise InvalidWorkspaceLease("workspace lease has expired")
        return row

    def _validated_lease_path(self, row: sqlite3.Row) -> Path:
        raw = Path(str(row["worktree_path"]))
        if raw.is_symlink():
            raise InvalidWorkspaceLease("workspace path cannot be a symlink")
        path = raw.resolve()
        _require_contained(self.root, path)
        if path.parent != self.root or path.name != row["run_id"] or not path.is_dir():
            raise InvalidWorkspaceLease("workspace path no longer matches the narrow-root manifest")
        return path

    @staticmethod
    def _discover_changed_paths(workspace: Path) -> list[str]:
        commands = (
            ["diff", "--name-only", "-z", "--diff-filter=ACMRTUXB", "HEAD"],
            ["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRTUXB", "HEAD"],
            ["ls-files", "--others", "--exclude-standard", "-z"],
        )
        found: list[str] = []
        for args in commands:
            payload = _git_bytes(workspace, args)
            for raw in payload.split(b"\0"):
                if raw:
                    found.append(_normalize_artifact_path(os.fsdecode(raw)))
        return found

    def _hash_artifact(
        self, workspace: Path, run_id: str, relative: str, discovered_at: str
    ) -> Artifact:
        candidate = workspace.joinpath(*PurePosixPath(relative).parts)
        current = workspace
        for part in PurePosixPath(relative).parts:
            current = current / part
            try:
                if current.is_symlink():
                    raise ArtifactError(f"artifact path cannot traverse symlinks: {relative}")
            except OSError as exc:
                raise ArtifactError(f"artifact path cannot be inspected: {relative}") from exc
        _require_contained(workspace, candidate.resolve(strict=False))

        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(candidate, flags)
        except (FileNotFoundError, IsADirectoryError, OSError) as exc:
            raise ArtifactError(f"artifact must be an existing regular file: {relative}") from exc
        digest = hashlib.sha256()
        total = 0
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise ArtifactError(f"artifact must be a regular file: {relative}")
            if before.st_size > self.max_file_bytes:
                raise ArtifactLimitExceeded(
                    f"artifact {relative!r} exceeds {self.max_file_bytes} bytes"
                )
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > self.max_file_bytes:
                    raise ArtifactLimitExceeded(
                        f"artifact {relative!r} exceeds {self.max_file_bytes} bytes"
                    )
                digest.update(chunk)
            after = os.fstat(fd)
        finally:
            os.close(fd)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ArtifactError(f"artifact changed while being hashed: {relative}")
        return Artifact(
            run_id=run_id,
            path=relative,
            size_bytes=total,
            sha256=digest.hexdigest(),
            modified_at=_iso(datetime.fromtimestamp(after.st_mtime, timezone.utc)),
            discovered_at=discovered_at,
        )

    def _migrate(self) -> None:
        with self.store.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS workspace_manifests (
                    run_id TEXT PRIMARY KEY,
                    bot_name TEXT NOT NULL DEFAULT '',
                    repo_path TEXT NOT NULL,
                    requested_ref TEXT NOT NULL,
                    commit_hash TEXT NOT NULL,
                    worktree_path TEXT NOT NULL UNIQUE,
                    lease_token TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN (
                        'creating', 'active', 'completed', 'failed',
                        'cancelled', 'stale', 'cleaned'
                    )),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    lease_expires_at TEXT NOT NULL,
                    finalized_at TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS workspace_manifests_state_lease
                    ON workspace_manifests(state, lease_expires_at);
                CREATE TABLE IF NOT EXISTS workspace_artifacts (
                    run_id TEXT NOT NULL REFERENCES workspace_manifests(run_id) ON DELETE CASCADE,
                    path TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    modified_at TEXT NOT NULL,
                    discovered_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, path)
                );
                CREATE TABLE IF NOT EXISTS workspace_execution_bindings (
                    run_id TEXT PRIMARY KEY,
                    workspace_run_id TEXT NOT NULL REFERENCES workspace_manifests(run_id),
                    bot_name TEXT NOT NULL,
                    auto_finalize INTEGER NOT NULL CHECK(auto_finalize IN (0, 1)),
                    artifact_paths_json TEXT NOT NULL,
                    lease_seconds REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS workspace_execution_workspace
                    ON workspace_execution_bindings(workspace_run_id);
                """
            )
            columns = {
                str(row["name"])
                for row in db.execute(
                    "PRAGMA table_info(workspace_execution_bindings)"
                ).fetchall()
            }
            if "lease_seconds" not in columns:
                db.execute(
                    "ALTER TABLE workspace_execution_bindings "
                    "ADD COLUMN lease_seconds REAL NOT NULL DEFAULT 3600"
                )


def _prepare_narrow_root(value: str | Path) -> Path:
    if not isinstance(value, (str, Path)) or not str(value) or _CONTROL_RE.search(str(value)):
        raise WorkspaceValidationError("workspace root is invalid")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise WorkspaceValidationError("workspace root must be an absolute path")
    home = Path.home().resolve()
    if path == Path(path.anchor) or path == home or len(path.parts) < 3:
        raise WorkspaceValidationError("workspace root is too broad")
    if path.is_symlink():
        raise WorkspaceValidationError("workspace root cannot be a symlink")
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise WorkspaceValidationError("workspace root cannot be a symlink")
    root = path.resolve()
    if root == Path(root.anchor) or root == home or len(root.parts) < 3:
        raise WorkspaceValidationError("workspace root is too broad")
    if not root.is_dir():
        raise WorkspaceValidationError("workspace root must be a real directory")
    return root


def _validate_run_id(value: str) -> str:
    if not isinstance(value, str) or not _RUN_ID_RE.fullmatch(value):
        raise WorkspaceValidationError(
            "run_id must be 1-128 characters using letters, digits, '.', '_' or '-'"
        )
    if value in {".", ".."}:
        raise WorkspaceValidationError("run_id cannot be a dot path")
    return value


def _validate_bot_name(value: str) -> str:
    if value == "":
        return ""
    if not isinstance(value, str) or not _BOT_ID_RE.fullmatch(value):
        raise WorkspaceValidationError("bot_name is invalid")
    return value


def _validate_ref(value: str) -> str:
    if not isinstance(value, str) or not _REF_RE.fullmatch(value):
        raise WorkspaceValidationError("git ref contains unsafe characters")
    if (
        value.startswith("-")
        or value.endswith((".", "/"))
        or ".." in value
        or "@{" in value
        or "//" in value
        or value == "@"
    ):
        raise WorkspaceValidationError("git ref is not a safe revision name")
    return value


def _normalize_artifact_path(value: str | Path) -> str:
    if not isinstance(value, (str, Path)):
        raise ArtifactError("artifact path must be a string or Path")
    text = os.fspath(value)
    if not isinstance(text, str) or not text or _CONTROL_RE.search(text) or "\\" in text:
        raise ArtifactError("artifact path is invalid")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ArtifactError("artifact path must be a normalized relative path")
    if path.parts[0] == ".git":
        raise ArtifactError("git administrative files cannot be artifacts")
    return path.as_posix()


def _positive_limit(value: int, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > maximum:
        raise WorkspaceValidationError(f"{name} must be an integer from 1 to {maximum}")
    return value


def _lease_delta(value: float) -> timedelta:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0 or value > 86_400:
        raise WorkspaceValidationError("lease_seconds must be greater than 0 and at most 86400")
    return timedelta(seconds=float(value))


def _require_contained(root: Path, candidate: Path) -> None:
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise WorkspaceValidationError(f"path escapes configured workspace root: {candidate}") from exc


def _contains(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _git(cwd: Path, args: Sequence[str], *, timeout: float = 30) -> str:
    return os.fsdecode(_git_bytes(cwd, args, timeout=timeout))


def _git_bytes(cwd: Path, args: Sequence[str], *, timeout: float = 30) -> bytes:
    if isinstance(args, (str, bytes)) or not all(isinstance(arg, str) for arg in args):
        raise WorkspaceValidationError("git commands require an argv list")
    argv = ["git", "-c", "core.hooksPath=/dev/null", "-C", str(cwd), *args]
    git_env = os.environ.copy()
    # Repository-redirection variables must not silently make validation and
    # worktree operations target a different repository than ``cwd``.
    for key in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ):
        git_env.pop(key, None)
    git_env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_PAGER": "cat",
            "GIT_LFS_SKIP_SMUDGE": "1",
        }
    )
    try:
        completed = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
            shell=False,
            env=git_env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitWorkspaceError("git command could not complete") from exc
    if completed.returncode != 0:
        message = os.fsdecode(completed.stderr).strip().replace("\n", " ")
        raise GitWorkspaceError(f"git command failed: {message[:300]}")
    return completed.stdout


def _lease_from_row(row: sqlite3.Row) -> WorkspaceLease:
    return WorkspaceLease(
        run_id=str(row["run_id"]),
        token=str(row["lease_token"]),
        path=str(row["worktree_path"]),
        repo_path=str(row["repo_path"]),
        requested_ref=str(row["requested_ref"]),
        commit=str(row["commit_hash"]),
        lease_expires_at=str(row["lease_expires_at"]),
    )


def _artifact_from_row(row: sqlite3.Row) -> Artifact:
    return Artifact(
        run_id=str(row["run_id"]),
        path=str(row["path"]),
        size_bytes=int(row["size_bytes"]),
        sha256=str(row["sha256"]),
        modified_at=str(row["modified_at"]),
        discovered_at=str(row["discovered_at"]),
    )


def _manifest_from_rows(
    row: sqlite3.Row, artifact_rows: Iterable[sqlite3.Row]
) -> WorkspaceManifest:
    return WorkspaceManifest(
        run_id=str(row["run_id"]),
        bot_name=str(row["bot_name"]),
        repo_path=str(row["repo_path"]),
        requested_ref=str(row["requested_ref"]),
        commit=str(row["commit_hash"]),
        worktree_path=str(row["worktree_path"]),
        state=str(row["state"]),  # type: ignore[arg-type]
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        lease_expires_at=str(row["lease_expires_at"]),
        finalized_at=str(row["finalized_at"]),
        error=str(row["error"]),
        artifacts=tuple(_artifact_from_row(item) for item in artifact_rows),
    )


def _safe_error(exc: BaseException) -> str:
    # Persist a bounded class/reason only. Git stderr may contain absolute paths
    # or material filenames, so it is intentionally not copied into manifests.
    return f"{type(exc).__name__}:workspace_creation_failed"[:160]


def _safe_error_text(value: BaseException | str) -> str:
    if isinstance(value, BaseException):
        return f"{type(value).__name__}:workspace_finalization_failed"[:160]
    return str(value).replace("\x00", "")[:160]


def _coerce_utc(value: datetime | None) -> datetime:
    if value is None:
        return _utc_now()
    if value.tzinfo is None:
        raise WorkspaceValidationError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
