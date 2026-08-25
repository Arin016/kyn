"""Deterministic policy, quota leasing, and immutable action audit.

This module deliberately accepts only identifiers and low-cardinality outcomes.
It has no API for recording prompts, tool arguments, environment values, or
other raw payloads that could contain user data or secrets.
"""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from .store import Store


ApprovalMode = Literal["ask", "deny", "allow_list"]
ToolDecisionName = Literal["ask", "approve", "deny"]

_APPROVAL_MODES = frozenset({"ask", "deny", "allow_list"})
_TOOL_DECISIONS = frozenset({"ask", "approve", "deny"})
_RUN_OUTCOMES = frozenset({"accepted", "rejected", "complete", "failed", "cancelled"})
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]*$")


@dataclass(frozen=True, slots=True)
class Policy:
    approval_mode: ApprovalMode = "ask"
    allowed_tools: tuple[str, ...] = field(default_factory=tuple)
    denied_tools: tuple[str, ...] = field(default_factory=tuple)
    # Zero means unlimited. This keeps the default policy usable while making
    # every configured positive limit fail closed.
    max_turns_per_hour: int = 0
    max_concurrent_runs: int = 0
    max_daily_runs: int = 0


@dataclass(frozen=True, slots=True)
class ToolDecision:
    decision: ToolDecisionName
    reason: str


@dataclass(frozen=True, slots=True)
class RunLease:
    bot_name: str
    run_id: str
    token: str
    reserved_at: str


class QuotaExceeded(RuntimeError):
    def __init__(self, quota: str) -> None:
        self.quota = quota
        super().__init__(f"run rejected by {quota} quota")


class InvalidLease(RuntimeError):
    pass


class GovernanceStore:
    """Governance state sharing the application's existing SQLite database."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self._migrate()

    def set_policy(self, bot_name: str, policy: Policy) -> Policy:
        normalized = _normalize_policy(policy)
        now = _iso(_utc_now())
        with self.store.connect() as db:
            db.execute(
                """
                INSERT INTO governance_policies(
                    bot_name, approval_mode, allowed_tools_json, denied_tools_json,
                    max_turns_per_hour, max_concurrent_runs, max_daily_runs,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bot_name) DO UPDATE SET
                    approval_mode=excluded.approval_mode,
                    allowed_tools_json=excluded.allowed_tools_json,
                    denied_tools_json=excluded.denied_tools_json,
                    max_turns_per_hour=excluded.max_turns_per_hour,
                    max_concurrent_runs=excluded.max_concurrent_runs,
                    max_daily_runs=excluded.max_daily_runs,
                    updated_at=excluded.updated_at
                """,
                (
                    _identifier(bot_name, "bot_name", 128),
                    normalized.approval_mode,
                    json.dumps(normalized.allowed_tools),
                    json.dumps(normalized.denied_tools),
                    normalized.max_turns_per_hour,
                    normalized.max_concurrent_runs,
                    normalized.max_daily_runs,
                    now,
                    now,
                ),
            )
        return normalized

    def get_policy(self, bot_name: str) -> Policy:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM governance_policies WHERE bot_name = ?",
                (_identifier(bot_name, "bot_name", 128),),
            ).fetchone()
        if row is None:
            return Policy()
        return Policy(
            approval_mode=row["approval_mode"],
            allowed_tools=tuple(json.loads(row["allowed_tools_json"])),
            denied_tools=tuple(json.loads(row["denied_tools_json"])),
            max_turns_per_hour=int(row["max_turns_per_hour"]),
            max_concurrent_runs=int(row["max_concurrent_runs"]),
            max_daily_runs=int(row["max_daily_runs"]),
        )

    def evaluate_tool(
        self,
        bot_name: str,
        canonical_tool_name: str,
        request_id: str,
        title: str = "",
    ) -> ToolDecision:
        """Evaluate a canonical tool identifier without consulting ``title``.

        ``title`` is accepted only for compatibility with ACP permission events.
        It is model-authored display text: it is neither trusted nor persisted.
        """

        del request_id, title
        tool = _tool_name(canonical_tool_name)
        policy = self.get_policy(bot_name)
        denied = set(policy.denied_tools)
        allowed = set(policy.allowed_tools)

        if tool in denied:
            return ToolDecision("deny", "tool_denied")
        if policy.approval_mode == "deny":
            return ToolDecision("deny", "policy_deny")
        if policy.approval_mode == "allow_list":
            if tool in allowed:
                return ToolDecision("approve", "tool_allowed")
            return ToolDecision("deny", "tool_not_allowed")
        return ToolDecision("ask", "approval_required")

    def reserve_run(
        self,
        bot_name: str,
        run_id: str,
        now: datetime | None = None,
        *,
        actor: str = "system",
    ) -> RunLease:
        """Atomically reserve capacity or raise :class:`QuotaExceeded`.

        Hourly and daily limits use fixed UTC clock windows. An existing active
        reservation is idempotently returned for the same bot and run ID.
        """

        bot = _identifier(bot_name, "bot_name", 128)
        run = _identifier(run_id, "run_id", 160)
        timestamp = _coerce_utc(now)
        timestamp_text = _iso(timestamp)
        hour_start = timestamp.replace(minute=0, second=0, microsecond=0)
        day_start = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
        hour_end = hour_start + timedelta(hours=1)
        day_end = day_start + timedelta(days=1)
        policy = self.get_policy(bot)
        rejection: str | None = None
        lease: RunLease | None = None

        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM governance_run_leases WHERE run_id = ?", (run,)
            ).fetchone()
            if existing is not None:
                if existing["bot_name"] != bot or existing["status"] != "active":
                    raise InvalidLease("run ID is already associated with another or finished lease")
                return RunLease(bot, run, existing["lease_token"], existing["reserved_at"])

            active = int(
                db.execute(
                    "SELECT COUNT(*) FROM governance_run_leases WHERE bot_name = ? AND status = 'active'",
                    (bot,),
                ).fetchone()[0]
            )
            hourly = int(
                db.execute(
                    """
                    SELECT COUNT(*) FROM governance_run_leases
                    WHERE bot_name = ? AND reserved_at >= ? AND reserved_at < ?
                    """,
                    (bot, _iso(hour_start), _iso(hour_end)),
                ).fetchone()[0]
            )
            daily = int(
                db.execute(
                    """
                    SELECT COUNT(*) FROM governance_run_leases
                    WHERE bot_name = ? AND reserved_at >= ? AND reserved_at < ?
                    """,
                    (bot, _iso(day_start), _iso(day_end)),
                ).fetchone()[0]
            )

            if policy.max_concurrent_runs and active >= policy.max_concurrent_runs:
                rejection = "quota_concurrent"
            elif policy.max_turns_per_hour and hourly >= policy.max_turns_per_hour:
                rejection = "quota_hourly"
            elif policy.max_daily_runs and daily >= policy.max_daily_runs:
                rejection = "quota_daily"

            if rejection is None:
                token = secrets.token_urlsafe(24)
                db.execute(
                    """
                    INSERT INTO governance_run_leases(
                        run_id, bot_name, lease_token, status, reserved_at
                    ) VALUES (?, ?, ?, 'active', ?)
                    """,
                    (run, bot, token, timestamp_text),
                )
                lease = RunLease(bot, run, token, timestamp_text)
                self._append_audit(
                    db, bot, run, "", "run_submission", actor,
                    "accepted", "within_limits", timestamp_text, "",
                )
            else:
                self._append_audit(
                    db, bot, run, "", "run_submission", actor,
                    "rejected", rejection, timestamp_text, "",
                )

        if rejection is not None:
            raise QuotaExceeded(rejection.removeprefix("quota_"))
        assert lease is not None
        return lease

    def finish_run(
        self,
        lease: RunLease,
        outcome: Literal["complete", "failed", "cancelled"] = "complete",
        now: datetime | None = None,
        *,
        actor: str = "system",
        reason: str = "run_finished",
    ) -> bool:
        if outcome not in {"complete", "failed", "cancelled"}:
            raise ValueError("outcome must be complete, failed, or cancelled")
        timestamp = _iso(_coerce_utc(now))
        safe_reason = _reason(reason)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM governance_run_leases WHERE run_id = ?",
                (lease.run_id,),
            ).fetchone()
            if row is None or not secrets.compare_digest(row["lease_token"], lease.token):
                raise InvalidLease("lease token is invalid")
            if row["bot_name"] != lease.bot_name:
                raise InvalidLease("lease belongs to a different bot")
            if row["status"] != "active":
                return False
            db.execute(
                """
                UPDATE governance_run_leases
                SET status = 'finished', finished_at = ?, outcome = ?
                WHERE run_id = ? AND status = 'active'
                """,
                (timestamp, outcome, lease.run_id),
            )
            self._append_audit(
                db, lease.bot_name, lease.run_id, "", "run_outcome", actor,
                outcome, safe_reason, timestamp, "",
            )
        return True

    def reconcile_run_leases(self, now: datetime | None = None) -> int:
        """Release orphaned governance capacity after an interrupted commit.

        Durable completion and governance release are separate SQLite
        transactions. If the process dies between them, this startup pass makes
        the durable ledger authoritative and closes terminal or missing leases.
        """

        timestamp = _iso(_coerce_utc(now))
        reconciled = 0
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            durable_exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'durable_runs'"
            ).fetchone()
            if durable_exists is None:
                return 0
            rows = db.execute(
                """
                SELECT lease.run_id, lease.bot_name, durable.status AS durable_status
                FROM governance_run_leases AS lease
                LEFT JOIN durable_runs AS durable ON durable.run_id = lease.run_id
                WHERE lease.status = 'active'
                  AND (durable.run_id IS NULL OR durable.status IN ('complete', 'failed', 'cancelled'))
                ORDER BY lease.run_id
                """
            ).fetchall()
            for row in rows:
                outcome = row["durable_status"] or "cancelled"
                reason = "recovered_terminal" if row["durable_status"] else "durable_missing"
                cursor = db.execute(
                    """
                    UPDATE governance_run_leases
                    SET status = 'finished', finished_at = ?, outcome = ?
                    WHERE run_id = ? AND status = 'active'
                    """,
                    (timestamp, outcome, row["run_id"]),
                )
                if cursor.rowcount:
                    self._append_audit(
                        db,
                        row["bot_name"],
                        row["run_id"],
                        "",
                        "run_outcome",
                        "recovery",
                        outcome,
                        reason,
                        timestamp,
                        "",
                    )
                    reconciled += 1
        return reconciled

    def record_permission_decision(
        self,
        bot_name: str,
        run_id: str,
        request_id: str,
        canonical_tool_name: str,
        decision: ToolDecisionName,
        *,
        actor: str,
        reason: str,
        now: datetime | None = None,
    ) -> int:
        if decision not in _TOOL_DECISIONS:
            raise ValueError("decision must be ask, approve, or deny")
        with self.store.connect() as db:
            return self._append_audit(
                db,
                _identifier(bot_name, "bot_name", 128),
                _identifier(run_id, "run_id", 160),
                _identifier(request_id, "request_id", 160),
                "permission_decision",
                actor,
                decision,
                _reason(reason),
                _iso(_coerce_utc(now)),
                _tool_name(canonical_tool_name),
            )

    def list_audit(
        self,
        *,
        bot_name: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
        before_id: int | None = None,
    ) -> list[dict[str, Any]]:
        bounded = min(max(int(limit), 1), 500)
        clauses: list[str] = []
        values: list[Any] = []
        if bot_name is not None:
            clauses.append("bot_name = ?")
            values.append(_identifier(bot_name, "bot_name", 128))
        if run_id is not None:
            clauses.append("run_id = ?")
            values.append(_identifier(run_id, "run_id", 160))
        if before_id is not None:
            clauses.append("id < ?")
            values.append(int(before_id))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(bounded)
        with self.store.connect() as db:
            rows = db.execute(
                f"""
                SELECT id, bot_name, run_id, request_id, event_type, actor,
                       outcome, reason, canonical_tool_name, created_at
                FROM governance_audit {where} ORDER BY id DESC LIMIT ?
                """,
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    def audit_summary(
        self, *, bot_name: str | None = None, since: datetime | None = None
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if bot_name is not None:
            clauses.append("bot_name = ?")
            values.append(_identifier(bot_name, "bot_name", 128))
        if since is not None:
            clauses.append("created_at >= ?")
            values.append(_iso(_coerce_utc(since)))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.store.connect() as db:
            rows = db.execute(
                f"""
                SELECT event_type, outcome, reason, COUNT(*) AS count
                FROM governance_audit {where}
                GROUP BY event_type, outcome, reason
                ORDER BY event_type, outcome, reason
                """,
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    def _append_audit(
        self,
        db: sqlite3.Connection,
        bot_name: str,
        run_id: str,
        request_id: str,
        event_type: str,
        actor: str,
        outcome: str,
        reason: str,
        created_at: str,
        canonical_tool_name: str,
    ) -> int:
        if outcome not in _RUN_OUTCOMES | _TOOL_DECISIONS:
            raise ValueError("unsupported audit outcome")
        cursor = db.execute(
            """
            INSERT INTO governance_audit(
                bot_name, run_id, request_id, event_type, actor, outcome,
                reason, canonical_tool_name, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _identifier(bot_name, "bot_name", 128),
                _identifier(run_id, "run_id", 160),
                _optional_identifier(request_id, "request_id", 160),
                event_type,
                _bounded(actor, "actor", 80),
                outcome,
                _reason(reason),
                _optional_tool_name(canonical_tool_name),
                created_at,
            ),
        )
        return int(cursor.lastrowid)

    def _migrate(self) -> None:
        with self.store.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS governance_policies (
                    bot_name TEXT PRIMARY KEY REFERENCES bots(name) ON DELETE CASCADE,
                    approval_mode TEXT NOT NULL CHECK(approval_mode IN ('ask', 'deny', 'allow_list')),
                    allowed_tools_json TEXT NOT NULL DEFAULT '[]',
                    denied_tools_json TEXT NOT NULL DEFAULT '[]',
                    max_turns_per_hour INTEGER NOT NULL DEFAULT 0 CHECK(max_turns_per_hour >= 0),
                    max_concurrent_runs INTEGER NOT NULL DEFAULT 0 CHECK(max_concurrent_runs >= 0),
                    max_daily_runs INTEGER NOT NULL DEFAULT 0 CHECK(max_daily_runs >= 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS governance_run_leases (
                    run_id TEXT PRIMARY KEY,
                    bot_name TEXT NOT NULL REFERENCES bots(name) ON DELETE CASCADE,
                    lease_token TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK(status IN ('active', 'finished')),
                    reserved_at TEXT NOT NULL,
                    finished_at TEXT,
                    outcome TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS governance_leases_bot_status
                    ON governance_run_leases(bot_name, status);
                CREATE INDEX IF NOT EXISTS governance_leases_bot_reserved
                    ON governance_run_leases(bot_name, reserved_at);
                CREATE TABLE IF NOT EXISTS governance_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_name TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    event_type TEXT NOT NULL CHECK(event_type IN ('run_submission', 'run_outcome', 'permission_decision')),
                    actor TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    canonical_tool_name TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS governance_audit_bot_created
                    ON governance_audit(bot_name, created_at);
                CREATE INDEX IF NOT EXISTS governance_audit_run
                    ON governance_audit(run_id, id);
                CREATE TRIGGER IF NOT EXISTS governance_audit_no_update
                BEFORE UPDATE ON governance_audit
                BEGIN
                    SELECT RAISE(ABORT, 'governance audit rows are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS governance_audit_no_delete
                BEFORE DELETE ON governance_audit
                BEGIN
                    SELECT RAISE(ABORT, 'governance audit rows are immutable');
                END;
                """
            )


def _normalize_policy(policy: Policy) -> Policy:
    if policy.approval_mode not in _APPROVAL_MODES:
        raise ValueError("approval_mode must be ask, deny, or allow_list")
    quotas = (
        policy.max_turns_per_hour,
        policy.max_concurrent_runs,
        policy.max_daily_runs,
    )
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in quotas):
        raise ValueError("quota values must be non-negative integers")
    return Policy(
        approval_mode=policy.approval_mode,
        allowed_tools=tuple(sorted({_tool_name(value) for value in policy.allowed_tools})),
        denied_tools=tuple(sorted({_tool_name(value) for value in policy.denied_tools})),
        max_turns_per_hour=policy.max_turns_per_hour,
        max_concurrent_runs=policy.max_concurrent_runs,
        max_daily_runs=policy.max_daily_runs,
    )


def _tool_name(value: str) -> str:
    return _identifier(value, "canonical_tool_name", 200).lower()


def _optional_tool_name(value: str) -> str:
    return _tool_name(value) if value else ""


def _reason(value: str) -> str:
    reason = _identifier(value, "reason", 64).lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_]*", reason):
        raise ValueError("reason must be a low-cardinality snake_case code")
    return reason


def _identifier(value: str, label: str, maximum: int) -> str:
    text = _bounded(value, label, maximum)
    if not _SAFE_IDENTIFIER.fullmatch(text):
        raise ValueError(f"{label} contains unsupported characters")
    return text


def _optional_identifier(value: str, label: str, maximum: int) -> str:
    return _identifier(value, label, maximum) if value else ""


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
    current = value or _utc_now()
    if current.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return current.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="microseconds")
