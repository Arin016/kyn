"""Crash-safe SQLite repository for durable run execution.

The repository stores the user message because replay after a daemon crash
requires it.  It intentionally has no columns or APIs for event payloads, tool
arguments, environment data, credentials, or provider responses.

Recovery is at-least-once: a run whose worker disappears is requeued and its
message may execute again. Callers must keep side-effecting tools independently
idempotent or approval-gated.
"""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from .store import Store


RunStatus = Literal[
    "queued", "running", "waiting_permission", "complete", "failed", "cancelled"
]
TerminalStatus = Literal["complete", "failed", "cancelled"]

_ALL_STATUSES = frozenset(
    {"queued", "running", "waiting_permission", "complete", "failed", "cancelled"}
)
_ACTIVE_STATUSES = frozenset({"running", "waiting_permission"})
_TERMINAL_STATUSES = frozenset({"complete", "failed", "cancelled"})


@dataclass(frozen=True, slots=True)
class DurableRun:
    run_id: str
    bot_name: str
    message: str
    actor: str
    status: RunStatus
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None
    attempt: int
    lease_owner: str
    lease_expires_at: str | None


@dataclass(frozen=True, slots=True)
class RunLease:
    run: DurableRun
    token: str
    owner: str
    expires_at: str


class RunConflict(RuntimeError):
    pass


class InvalidTransition(RuntimeError):
    pass


class InvalidLease(RuntimeError):
    pass


class RunRepository:
    """Durable run queue sharing the application's existing ``Store`` DB."""

    def __init__(self, store: Store, *, max_terminal_runs: int = 5_000) -> None:
        if not isinstance(max_terminal_runs, int) or isinstance(max_terminal_runs, bool):
            raise TypeError("max_terminal_runs must be an integer")
        if max_terminal_runs < 0:
            raise ValueError("max_terminal_runs cannot be negative")
        self.store = store
        self.max_terminal_runs = max_terminal_runs
        self._migrate()

    def enqueue(
        self,
        run_id: str,
        bot_name: str,
        message: str,
        *,
        actor: str = "user",
        now: datetime | None = None,
    ) -> DurableRun:
        run = _bounded(run_id, "run_id", 160)
        bot = _bounded(bot_name, "bot_name", 128)
        safe_actor = _bounded(actor, "actor", 80)
        safe_message = _message(message)
        timestamp = _iso(_coerce_utc(now))
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM durable_runs WHERE run_id = ?", (run,)
            ).fetchone()
            if existing is not None:
                if (
                    existing["bot_name"] == bot
                    and existing["message"] == safe_message
                    and existing["actor"] == safe_actor
                ):
                    return _run_from_row(existing)
                raise RunConflict("run ID already exists with different immutable fields")
            db.execute(
                """
                INSERT INTO durable_runs(
                    run_id, bot_name, message, actor, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'queued', ?, ?)
                """,
                (run, bot, safe_message, safe_actor, timestamp, timestamp),
            )
            row = db.execute("SELECT * FROM durable_runs WHERE run_id = ?", (run,)).fetchone()
        assert row is not None
        return _run_from_row(row)

    def get(self, run_id: str) -> DurableRun | None:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM durable_runs WHERE run_id = ?",
                (_bounded(run_id, "run_id", 160),),
            ).fetchone()
        return _run_from_row(row) if row is not None else None

    def list_runs(
        self,
        *,
        bot_name: str | None = None,
        status: RunStatus | None = None,
        limit: int = 100,
        after_created_at: str | None = None,
        after_run_id: str | None = None,
    ) -> list[DurableRun]:
        bounded_limit = min(max(int(limit), 1), 1_000)
        clauses: list[str] = []
        values: list[Any] = []
        if bot_name is not None:
            clauses.append("bot_name = ?")
            values.append(_bounded(bot_name, "bot_name", 128))
        if status is not None:
            if status not in _ALL_STATUSES:
                raise ValueError("unknown run status")
            clauses.append("status = ?")
            values.append(status)
        if (after_created_at is None) != (after_run_id is None):
            raise ValueError("both pagination cursor fields must be provided")
        if after_created_at is not None and after_run_id is not None:
            clauses.append("(created_at > ? OR (created_at = ? AND run_id > ?))")
            values.extend(
                [
                    _bounded(after_created_at, "after_created_at", 64),
                    _bounded(after_created_at, "after_created_at", 64),
                    _bounded(after_run_id, "after_run_id", 160),
                ]
            )
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(bounded_limit)
        with self.store.connect() as db:
            rows = db.execute(
                f"SELECT * FROM durable_runs {where} ORDER BY created_at, run_id LIMIT ?",
                values,
            ).fetchall()
        return [_run_from_row(row) for row in rows]

    def claim(
        self,
        run_id: str,
        worker_id: str,
        *,
        lease_seconds: int = 60,
        now: datetime | None = None,
    ) -> RunLease | None:
        run = _bounded(run_id, "run_id", 160)
        return self._claim_where(
            "run_id = ?", (run,), worker_id, lease_seconds, now
        )

    def claim_next(
        self,
        worker_id: str,
        *,
        bot_name: str | None = None,
        lease_seconds: int = 60,
        now: datetime | None = None,
    ) -> RunLease | None:
        if bot_name is None:
            return self._claim_where("1 = 1", (), worker_id, lease_seconds, now)
        return self._claim_where(
            "bot_name = ?",
            (_bounded(bot_name, "bot_name", 128),),
            worker_id,
            lease_seconds,
            now,
        )

    def renew_lease(
        self,
        run_id: str,
        token: str,
        *,
        lease_seconds: int = 60,
        now: datetime | None = None,
    ) -> RunLease:
        run = _bounded(run_id, "run_id", 160)
        lease_token = _bounded(token, "lease token", 256)
        timestamp = _coerce_utc(now)
        expires = timestamp + timedelta(seconds=_lease_seconds(lease_seconds))
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._require_active_lease(db, run, lease_token, timestamp)
            db.execute(
                "UPDATE durable_runs SET lease_expires_at = ?, updated_at = ? WHERE run_id = ?",
                (_iso(expires), _iso(timestamp), run),
            )
            updated = db.execute("SELECT * FROM durable_runs WHERE run_id = ?", (run,)).fetchone()
        assert updated is not None
        durable = _run_from_row(updated)
        return RunLease(durable, lease_token, row["lease_owner"], _iso(expires))

    def mark_waiting_permission(
        self,
        run_id: str,
        token: str,
        *,
        now: datetime | None = None,
    ) -> DurableRun:
        timestamp = _coerce_utc(now)
        run = _bounded(run_id, "run_id", 160)
        lease_token = _bounded(token, "lease token", 256)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_active_lease(db, run, lease_token, timestamp)
            db.execute(
                "UPDATE durable_runs SET status = 'waiting_permission', updated_at = ? WHERE run_id = ?",
                (_iso(timestamp), run),
            )
            updated = db.execute("SELECT * FROM durable_runs WHERE run_id = ?", (run,)).fetchone()
        assert updated is not None
        return _run_from_row(updated)

    def mark_running(
        self,
        run_id: str,
        token: str,
        *,
        now: datetime | None = None,
    ) -> DurableRun:
        timestamp = _coerce_utc(now)
        run = _bounded(run_id, "run_id", 160)
        lease_token = _bounded(token, "lease token", 256)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_active_lease(db, run, lease_token, timestamp)
            db.execute(
                "UPDATE durable_runs SET status = 'running', updated_at = ? WHERE run_id = ?",
                (_iso(timestamp), run),
            )
            updated = db.execute("SELECT * FROM durable_runs WHERE run_id = ?", (run,)).fetchone()
        assert updated is not None
        return _run_from_row(updated)

    def requeue_stale(self, now: datetime | None = None) -> int:
        timestamp = _iso(_coerce_utc(now))
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                """
                UPDATE durable_runs
                SET status = 'queued', lease_owner = '', lease_token = '',
                    lease_expires_at = NULL, updated_at = ?
                WHERE status IN ('running', 'waiting_permission')
                  AND lease_expires_at <= ?
                """,
                (timestamp, timestamp),
            )
            return int(cursor.rowcount)

    def recover_startup(self, now: datetime | None = None) -> int:
        """Requeue all abandoned active runs when the single daemon starts."""

        timestamp = _iso(_coerce_utc(now))
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                """
                UPDATE durable_runs
                SET status = 'queued', lease_owner = '', lease_token = '',
                    lease_expires_at = NULL, updated_at = ?
                WHERE status IN ('running', 'waiting_permission')
                """,
                (timestamp,),
            )
            return int(cursor.rowcount)

    def finish(
        self,
        run_id: str,
        token: str,
        status: TerminalStatus,
        *,
        now: datetime | None = None,
    ) -> DurableRun:
        if status not in _TERMINAL_STATUSES:
            raise ValueError("terminal status must be complete, failed, or cancelled")
        timestamp = _coerce_utc(now)
        run = _bounded(run_id, "run_id", 160)
        lease_token = _bounded(token, "lease token", 256)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_active_lease(db, run, lease_token, timestamp)
            db.execute(
                """
                UPDATE durable_runs
                SET status = ?, updated_at = ?, finished_at = ?,
                    lease_owner = '', lease_token = '', lease_expires_at = NULL
                WHERE run_id = ?
                """,
                (status, _iso(timestamp), _iso(timestamp), run),
            )
            updated = db.execute("SELECT * FROM durable_runs WHERE run_id = ?", (run,)).fetchone()
            self._prune_db(db, self.max_terminal_runs, None)
        assert updated is not None
        return _run_from_row(updated)

    def cancel_queued(
        self, run_id: str, *, now: datetime | None = None
    ) -> DurableRun:
        timestamp = _iso(_coerce_utc(now))
        run = _bounded(run_id, "run_id", 160)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM durable_runs WHERE run_id = ?", (run,)).fetchone()
            if row is None:
                raise KeyError(run)
            if row["status"] != "queued":
                raise InvalidTransition("only a queued run can be cancelled without a lease")
            db.execute(
                """
                UPDATE durable_runs SET status = 'cancelled', updated_at = ?, finished_at = ?
                WHERE run_id = ?
                """,
                (timestamp, timestamp, run),
            )
            updated = db.execute("SELECT * FROM durable_runs WHERE run_id = ?", (run,)).fetchone()
            self._prune_db(db, self.max_terminal_runs, None)
        assert updated is not None
        return _run_from_row(updated)

    def prune(
        self,
        *,
        max_terminal_runs: int | None = None,
        older_than: datetime | None = None,
    ) -> int:
        maximum = self.max_terminal_runs if max_terminal_runs is None else int(max_terminal_runs)
        if maximum < 0:
            raise ValueError("max_terminal_runs cannot be negative")
        threshold = _iso(_coerce_utc(older_than)) if older_than is not None else None
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._prune_db(db, maximum, threshold)

    def _claim_where(
        self,
        where: str,
        parameters: tuple[Any, ...],
        worker_id: str,
        lease_seconds: int,
        now: datetime | None,
    ) -> RunLease | None:
        owner = _bounded(worker_id, "worker_id", 128)
        timestamp = _coerce_utc(now)
        expires = timestamp + timedelta(seconds=_lease_seconds(lease_seconds))
        token = secrets.token_urlsafe(24)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                f"""
                SELECT * FROM durable_runs
                WHERE status = 'queued' AND ({where})
                ORDER BY created_at, run_id LIMIT 1
                """,
                parameters,
            ).fetchone()
            if row is None:
                return None
            db.execute(
                """
                UPDATE durable_runs
                SET status = 'running', lease_owner = ?, lease_token = ?,
                    lease_expires_at = ?, updated_at = ?,
                    started_at = COALESCE(started_at, ?), attempt = attempt + 1
                WHERE run_id = ? AND status = 'queued'
                """,
                (owner, token, _iso(expires), _iso(timestamp), _iso(timestamp), row["run_id"]),
            )
            updated = db.execute(
                "SELECT * FROM durable_runs WHERE run_id = ?", (row["run_id"],)
            ).fetchone()
        assert updated is not None
        durable = _run_from_row(updated)
        return RunLease(durable, token, owner, _iso(expires))

    def _require_active_lease(
        self,
        db: sqlite3.Connection,
        run_id: str,
        token: str,
        now: datetime,
    ) -> sqlite3.Row:
        row = db.execute("SELECT * FROM durable_runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        if row["status"] not in _ACTIVE_STATUSES:
            raise InvalidTransition("run is not active")
        if not row["lease_token"] or not secrets.compare_digest(row["lease_token"], token):
            raise InvalidLease("lease token is invalid")
        if row["lease_expires_at"] <= _iso(now):
            raise InvalidLease("lease has expired")
        return row

    def _prune_db(
        self, db: sqlite3.Connection, maximum: int, older_than: str | None
    ) -> int:
        deleted = 0
        if older_than is not None:
            cursor = db.execute(
                """
                DELETE FROM durable_runs
                WHERE status IN ('complete', 'failed', 'cancelled')
                  AND finished_at < ?
                """,
                (older_than,),
            )
            deleted += int(cursor.rowcount)
        cursor = db.execute(
            """
            DELETE FROM durable_runs
            WHERE status IN ('complete', 'failed', 'cancelled')
              AND run_id NOT IN (
                  SELECT run_id FROM durable_runs
                  WHERE status IN ('complete', 'failed', 'cancelled')
                  ORDER BY finished_at DESC, run_id DESC LIMIT ?
              )
            """,
            (maximum,),
        )
        return deleted + int(cursor.rowcount)

    def _migrate(self) -> None:
        with self.store.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS durable_runs (
                    run_id TEXT PRIMARY KEY,
                    bot_name TEXT NOT NULL REFERENCES bots(name) ON DELETE CASCADE,
                    message TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'queued', 'running', 'waiting_permission',
                        'complete', 'failed', 'cancelled'
                    )),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    attempt INTEGER NOT NULL DEFAULT 0 CHECK(attempt >= 0),
                    lease_owner TEXT NOT NULL DEFAULT '',
                    lease_token TEXT NOT NULL DEFAULT '',
                    lease_expires_at TEXT
                );
                CREATE INDEX IF NOT EXISTS durable_runs_queue
                    ON durable_runs(status, created_at, run_id);
                CREATE INDEX IF NOT EXISTS durable_runs_bot_status
                    ON durable_runs(bot_name, status, created_at);
                CREATE INDEX IF NOT EXISTS durable_runs_lease_expiry
                    ON durable_runs(status, lease_expires_at);
                """
            )


def _run_from_row(row: sqlite3.Row) -> DurableRun:
    return DurableRun(
        run_id=row["run_id"],
        bot_name=row["bot_name"],
        message=row["message"],
        actor=row["actor"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        attempt=int(row["attempt"]),
        lease_owner=row["lease_owner"],
        lease_expires_at=row["lease_expires_at"],
    )


def _lease_seconds(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 86_400:
        raise ValueError("lease_seconds must be an integer from 1 to 86400")
    return value


def _message(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("message must be a string")
    if not value.strip():
        raise ValueError("message must not be blank")
    if len(value) > 1_000_000:
        raise ValueError("message exceeds 1000000 characters")
    return value


def _bounded(value: str, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{label} must not be blank")
    if len(text) > maximum:
        raise ValueError(f"{label} exceeds {maximum} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in text):
        raise ValueError(f"{label} contains control characters")
    return text


def _coerce_utc(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return timestamp.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="microseconds")
