from __future__ import annotations

import asyncio
import sqlite3
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Literal

from .store import Store


TriggerKind = Literal["interval", "once"]
Clock = Callable[[], datetime]
Submit = Callable[[str, str], Awaitable[object]]

MIN_INTERVAL_SECONDS = 60


@dataclass(frozen=True, slots=True)
class Routine:
    id: str
    name: str
    bot_name: str
    prompt: str
    enabled: bool
    trigger_kind: TriggerKind
    interval_seconds: int | None
    run_at: str | None
    last_run_at: str | None
    next_run_at: str | None
    created_at: str
    updated_at: str


class RoutineNotFound(KeyError):
    """Raised when a routine id does not exist."""


class RoutineStore:
    """Durable routine definitions and transactional scheduler leases."""

    def __init__(
        self,
        store: Store,
        *,
        min_interval_seconds: int = MIN_INTERVAL_SECONDS,
    ) -> None:
        if min_interval_seconds < 1:
            raise ValueError("min_interval_seconds must be at least 1")
        self.store = store
        self.min_interval_seconds = int(min_interval_seconds)
        self._migrate()

    def create(
        self,
        *,
        name: str,
        bot_name: str,
        prompt: str,
        trigger_kind: TriggerKind,
        interval_seconds: int | None = None,
        run_at: str | datetime | None = None,
        enabled: bool = True,
        next_run_at: str | datetime | None = None,
        now: str | datetime | None = None,
        routine_id: str | None = None,
    ) -> Routine:
        current = _utc(now)
        normalized = self._validated(
            Routine(
                id=(routine_id or str(uuid.uuid4())).strip(),
                name=name.strip(),
                bot_name=bot_name.strip(),
                prompt=prompt.strip(),
                enabled=bool(enabled),
                trigger_kind=trigger_kind,
                interval_seconds=interval_seconds,
                run_at=_iso_optional(run_at),
                last_run_at=None,
                next_run_at=_iso_optional(next_run_at),
                created_at=_iso(current),
                updated_at=_iso(current),
            ),
            current,
        )
        with self.store.connect() as db:
            db.execute(
                """
                INSERT INTO routines(
                    id, name, bot_name, prompt, enabled, trigger_kind,
                    interval_seconds, run_at, last_run_at, next_run_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _values(normalized),
            )
        return normalized

    def put(self, routine: Routine, *, now: str | datetime | None = None) -> Routine:
        """Insert or replace a routine while preserving its explicit timestamps."""
        normalized = self._validated(routine, _utc(now))
        with self.store.connect() as db:
            db.execute(
                """
                INSERT INTO routines(
                    id, name, bot_name, prompt, enabled, trigger_kind,
                    interval_seconds, run_at, last_run_at, next_run_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name, bot_name=excluded.bot_name,
                    prompt=excluded.prompt, enabled=excluded.enabled,
                    trigger_kind=excluded.trigger_kind,
                    interval_seconds=excluded.interval_seconds,
                    run_at=excluded.run_at, last_run_at=excluded.last_run_at,
                    next_run_at=excluded.next_run_at,
                    updated_at=excluded.updated_at,
                    lease_owner=NULL, lease_until=NULL
                """,
                _values(normalized),
            )
        return normalized

    def get(self, routine_id: str) -> Routine | None:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM routines WHERE id = ?", (routine_id,)
            ).fetchone()
        return _from_row(row) if row is not None else None

    def list(
        self,
        *,
        bot_name: str | None = None,
        enabled: bool | None = None,
    ) -> list[Routine]:
        clauses: list[str] = []
        values: list[object] = []
        if bot_name is not None:
            clauses.append("bot_name = ?")
            values.append(bot_name)
        if enabled is not None:
            clauses.append("enabled = ?")
            values.append(int(enabled))
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.store.connect() as db:
            rows = db.execute(
                f"SELECT * FROM routines{where} ORDER BY created_at, id", values
            ).fetchall()
        return [_from_row(row) for row in rows]

    def update(
        self,
        routine_id: str,
        *,
        now: str | datetime | None = None,
        **changes: object,
    ) -> Routine:
        routine = self.get(routine_id)
        if routine is None:
            raise RoutineNotFound(routine_id)
        allowed = {
            "name",
            "bot_name",
            "prompt",
            "enabled",
            "trigger_kind",
            "interval_seconds",
            "run_at",
            "last_run_at",
            "next_run_at",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise TypeError(f"unsupported routine fields: {', '.join(sorted(unknown))}")
        current = _utc(now)
        for field in ("run_at", "last_run_at", "next_run_at"):
            if field in changes:
                changes[field] = _iso_optional(changes[field])  # type: ignore[arg-type]
        candidate = replace(routine, **changes, updated_at=_iso(current))
        timing_changed = bool(
            {"trigger_kind", "interval_seconds", "run_at"}.intersection(changes)
        )
        reenabled = changes.get("enabled") is True and not routine.enabled
        if timing_changed or reenabled:
            if candidate.trigger_kind == "interval":
                interval = candidate.interval_seconds
                if isinstance(interval, bool) or not isinstance(interval, int):
                    raise ValueError("interval_seconds must be an integer")
                candidate = replace(
                    candidate,
                    next_run_at=_iso(current + timedelta(seconds=interval)),
                )
            elif candidate.trigger_kind == "once" and candidate.run_at is not None:
                scheduled = _utc(candidate.run_at)
                # Resuming an already-completed or overdue one-shot means run
                # it once now, rather than displaying an active routine whose
                # next execution is permanently NULL or in the past.
                if reenabled and scheduled < current:
                    scheduled = current
                candidate = replace(candidate, next_run_at=_iso(scheduled))
        normalized = self._validated(candidate, current, compute_schedule=False)
        return self.put(normalized, now=current)

    def delete(self, routine_id: str) -> bool:
        with self.store.connect() as db:
            cursor = db.execute("DELETE FROM routines WHERE id = ?", (routine_id,))
        return cursor.rowcount > 0

    def due(
        self,
        *,
        now: str | datetime | None = None,
        limit: int = 100,
    ) -> list[Routine]:
        if limit < 1:
            return []
        timestamp = _iso(_utc(now))
        with self.store.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM routines
                WHERE enabled = 1
                  AND next_run_at IS NOT NULL
                  AND next_run_at <= ?
                  AND (lease_until IS NULL OR lease_until <= ?)
                ORDER BY next_run_at, created_at, id
                LIMIT ?
                """,
                (timestamp, timestamp, int(limit)),
            ).fetchall()
        return [_from_row(row) for row in rows]

    def claim_due(
        self,
        owner: str,
        *,
        now: str | datetime | None = None,
        lease_seconds: float = 300,
        limit: int = 100,
    ) -> list[Routine]:
        owner = owner.strip()
        if not owner:
            raise ValueError("lease owner must not be blank")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if limit < 1:
            return []
        current = _utc(now)
        timestamp = _iso(current)
        lease_until = _iso(current + timedelta(seconds=lease_seconds))
        with self.store.connect() as db:
            db.execute("PRAGMA busy_timeout = 5000")
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                """
                SELECT * FROM routines
                WHERE enabled = 1
                  AND next_run_at IS NOT NULL
                  AND next_run_at <= ?
                  AND (lease_until IS NULL OR lease_until <= ?)
                ORDER BY next_run_at, created_at, id
                LIMIT ?
                """,
                (timestamp, timestamp, int(limit)),
            ).fetchall()
            claimed: list[Routine] = []
            for row in rows:
                cursor = db.execute(
                    """
                    UPDATE routines SET lease_owner = ?, lease_until = ?
                    WHERE id = ?
                      AND enabled = 1
                      AND (lease_until IS NULL OR lease_until <= ?)
                    """,
                    (owner, lease_until, row["id"], timestamp),
                )
                if cursor.rowcount == 1:
                    claimed.append(_from_row(row))
        return claimed

    def mark_success(
        self,
        routine_id: str,
        owner: str,
        *,
        now: str | datetime | None = None,
    ) -> bool:
        current = _utc(now)
        timestamp = _iso(current)
        with self.store.connect() as db:
            row = db.execute(
                "SELECT trigger_kind, interval_seconds FROM routines "
                "WHERE id = ? AND lease_owner = ?",
                (routine_id, owner),
            ).fetchone()
            if row is None:
                return False
            if row["trigger_kind"] == "once":
                cursor = db.execute(
                    """
                    UPDATE routines
                    SET enabled = 0, last_run_at = ?, next_run_at = NULL,
                        lease_owner = NULL, lease_until = NULL, updated_at = ?
                    WHERE id = ? AND lease_owner = ?
                    """,
                    (timestamp, timestamp, routine_id, owner),
                )
            else:
                # Anchor to completion time so delayed ticks never create a
                # burst of historical catch-up executions.
                next_run = _iso(
                    current + timedelta(seconds=int(row["interval_seconds"]))
                )
                cursor = db.execute(
                    """
                    UPDATE routines
                    SET last_run_at = ?, next_run_at = ?, lease_owner = NULL,
                        lease_until = NULL, updated_at = ?
                    WHERE id = ? AND lease_owner = ?
                    """,
                    (timestamp, next_run, timestamp, routine_id, owner),
                )
        return cursor.rowcount == 1

    def mark_failure(
        self,
        routine_id: str,
        owner: str,
        *,
        now: str | datetime | None = None,
        backoff_seconds: float = 30,
    ) -> bool:
        if backoff_seconds < 0:
            raise ValueError("backoff_seconds must not be negative")
        current = _utc(now)
        timestamp = _iso(current)
        retry_at = _iso(current + timedelta(seconds=backoff_seconds))
        with self.store.connect() as db:
            cursor = db.execute(
                """
                UPDATE routines
                SET next_run_at = ?, lease_owner = NULL, lease_until = NULL,
                    updated_at = ?
                WHERE id = ? AND lease_owner = ?
                """,
                (retry_at, timestamp, routine_id, owner),
            )
        return cursor.rowcount == 1

    # Readable aliases for integrations that model claiming as completion.
    complete = mark_success
    fail = mark_failure

    def _validated(
        self,
        routine: Routine,
        now: datetime,
        *,
        compute_schedule: bool = True,
    ) -> Routine:
        if not routine.id or len(routine.id) > 200:
            raise ValueError("routine id must not be blank or exceed 200 characters")
        _validate_label(routine.name, "routine name")
        _validate_label(routine.bot_name, "bot name")
        if not routine.prompt or not routine.prompt.strip():
            raise ValueError("prompt must not be blank")
        if self.store.get_bot(routine.bot_name) is None:
            raise ValueError(f"bot {routine.bot_name!r} does not exist")
        if routine.trigger_kind not in ("interval", "once"):
            raise ValueError("trigger_kind must be 'interval' or 'once'")

        run_at = _iso_optional(routine.run_at)
        next_run_at = _iso_optional(routine.next_run_at)
        last_run_at = _iso_optional(routine.last_run_at)
        interval = routine.interval_seconds
        if routine.trigger_kind == "interval":
            if isinstance(interval, bool) or not isinstance(interval, int):
                raise ValueError("interval_seconds must be an integer")
            if interval < self.min_interval_seconds:
                raise ValueError(
                    f"interval_seconds must be at least {self.min_interval_seconds}"
                )
            if run_at is not None:
                raise ValueError("run_at is only valid for a once routine")
            if compute_schedule and next_run_at is None:
                next_run_at = _iso(now + timedelta(seconds=interval))
        else:
            if interval is not None:
                raise ValueError("interval_seconds is only valid for an interval routine")
            if run_at is None:
                raise ValueError("run_at is required for a once routine")
            if compute_schedule and next_run_at is None:
                next_run_at = run_at

        return replace(
            routine,
            name=routine.name.strip(),
            bot_name=routine.bot_name.strip(),
            prompt=routine.prompt.strip(),
            interval_seconds=interval,
            run_at=run_at,
            last_run_at=last_run_at,
            next_run_at=next_run_at,
            created_at=_iso_optional(routine.created_at) or _iso(now),
            updated_at=_iso_optional(routine.updated_at) or _iso(now),
        )

    def _migrate(self) -> None:
        with self.store.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS routines (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    bot_name TEXT NOT NULL REFERENCES bots(name) ON DELETE CASCADE,
                    prompt TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
                    trigger_kind TEXT NOT NULL CHECK(trigger_kind IN ('interval', 'once')),
                    interval_seconds INTEGER,
                    run_at TEXT,
                    last_run_at TEXT,
                    next_run_at TEXT,
                    lease_owner TEXT,
                    lease_until TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_routines_due
                    ON routines(enabled, next_run_at, lease_until);
                CREATE INDEX IF NOT EXISTS idx_routines_bot
                    ON routines(bot_name, created_at);
                """
            )


class Scheduler:
    """Poll due routines and submit them with bounded concurrency."""

    def __init__(
        self,
        service: RoutineStore,
        submit: Submit,
        *,
        clock: Clock | None = None,
        max_concurrency: int = 4,
        poll_seconds: float = 1,
        lease_seconds: float = 300,
        retry_backoff_seconds: float = 30,
        owner: str | None = None,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must not be negative")
        self.service = service
        self.submit = submit
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.max_concurrency = int(max_concurrency)
        self.poll_seconds = float(poll_seconds)
        self.lease_seconds = float(lease_seconds)
        self.retry_backoff_seconds = float(retry_backoff_seconds)
        self.owner = owner or f"scheduler-{uuid.uuid4()}"
        self._stop = asyncio.Event()
        self._tick_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._closed = False

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("scheduler is closed")
        if self._task is None:
            self._task = asyncio.create_task(
                self._run_loop(), name=f"kyn-scheduler:{self.owner}"
            )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        if self._task is not None:
            await self._task

    async def tick(self) -> int:
        if self._closed:
            return 0
        async with self._tick_lock:
            now = _utc(self.clock())
            claimed = self.service.claim_due(
                self.owner,
                now=now,
                lease_seconds=self.lease_seconds,
                limit=self.max_concurrency,
            )
            if not claimed:
                return 0
            await asyncio.gather(*(self._submit(routine) for routine in claimed))
            return len(claimed)

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            await self.tick()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                pass

    async def _submit(self, routine: Routine) -> None:
        try:
            await self.submit(routine.bot_name, routine.prompt)
        except asyncio.CancelledError:
            self.service.mark_failure(
                routine.id,
                self.owner,
                now=self.clock(),
                backoff_seconds=self.retry_backoff_seconds,
            )
            raise
        except Exception:
            self.service.mark_failure(
                routine.id,
                self.owner,
                now=self.clock(),
                backoff_seconds=self.retry_backoff_seconds,
            )
        else:
            self.service.mark_success(routine.id, self.owner, now=self.clock())


def _validate_label(value: str, label: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{label} must not be blank")
    if len(value.strip()) > 100:
        raise ValueError(f"{label} must not exceed 100 characters")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{label} must not contain control characters")


def _utc(value: str | datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat()


def _iso_optional(value: str | datetime | None) -> str | None:
    return None if value is None else _iso(_utc(value))


def _values(routine: Routine) -> tuple[object, ...]:
    return (
        routine.id,
        routine.name,
        routine.bot_name,
        routine.prompt,
        int(routine.enabled),
        routine.trigger_kind,
        routine.interval_seconds,
        routine.run_at,
        routine.last_run_at,
        routine.next_run_at,
        routine.created_at,
        routine.updated_at,
    )


def _from_row(row: sqlite3.Row) -> Routine:
    return Routine(
        id=row["id"],
        name=row["name"],
        bot_name=row["bot_name"],
        prompt=row["prompt"],
        enabled=bool(row["enabled"]),
        trigger_kind=row["trigger_kind"],
        interval_seconds=row["interval_seconds"],
        run_at=row["run_at"],
        last_run_at=row["last_run_at"],
        next_run_at=row["next_run_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
