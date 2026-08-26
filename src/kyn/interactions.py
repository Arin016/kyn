from __future__ import annotations

import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from .store import Store


InteractionStatus = Literal["pending", "resolved", "expired"]


@dataclass(frozen=True, slots=True)
class Interaction:
    id: str
    run_id: str
    bot_name: str
    actor: str
    kind: str
    request_id: str
    title: str
    tool_name: str
    status: InteractionStatus
    decision: str
    decided_by: str
    created_at: str
    resolved_at: str

    def summary(self) -> dict[str, Any]:
        return asdict(self)


class InteractionNotFound(KeyError):
    pass


class InteractionConflict(RuntimeError):
    pass


class InteractionStore:
    """Durable human-input ledger shared by the control room and channels."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self._migrate()

    def create_permission(
        self,
        *,
        run_id: str,
        bot_name: str,
        actor: str,
        request_id: str,
        title: str,
        tool_name: str,
    ) -> Interaction:
        interaction_id = uuid.uuid4().hex
        now = _now()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM interactions WHERE run_id=? AND request_id=?",
                (run_id, request_id),
            ).fetchone()
            if existing is not None:
                return _interaction(existing)
            db.execute(
                """
                INSERT INTO interactions(
                    id,run_id,bot_name,actor,kind,request_id,title,tool_name,
                    status,decision,decided_by,created_at,resolved_at
                ) VALUES (?,?,?,?,?,?,?,?, 'pending','','',?,'')
                """,
                (
                    interaction_id,
                    run_id,
                    bot_name,
                    actor,
                    "permission",
                    request_id,
                    title[:1000],
                    tool_name[:200],
                    now,
                ),
            )
            row = db.execute(
                "SELECT * FROM interactions WHERE id=?", (interaction_id,)
            ).fetchone()
        assert row is not None
        return _interaction(row)

    def get(self, interaction_id: str) -> Interaction | None:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM interactions WHERE id=?", (interaction_id,)
            ).fetchone()
        return None if row is None else _interaction(row)

    def require(self, interaction_id: str) -> Interaction:
        item = self.get(interaction_id)
        if item is None:
            raise InteractionNotFound(interaction_id)
        return item

    def list(
        self,
        *,
        bot_name: str | None = None,
        status: InteractionStatus | None = None,
        limit: int = 100,
    ) -> list[Interaction]:
        clauses: list[str] = []
        args: list[Any] = []
        if bot_name is not None:
            clauses.append("bot_name=?")
            args.append(bot_name)
        if status is not None:
            clauses.append("status=?")
            args.append(status)
        sql = "SELECT * FROM interactions"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC,id DESC LIMIT ?"
        args.append(min(max(int(limit), 1), 500))
        with self.store.connect() as db:
            rows = db.execute(sql, tuple(args)).fetchall()
        return [_interaction(row) for row in rows]

    def resolve(self, interaction_id: str, decision: str, *, actor: str) -> Interaction:
        if decision not in {"once", "reject"}:
            raise ValueError("decision must be once or reject")
        now = _now()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM interactions WHERE id=?", (interaction_id,)
            ).fetchone()
            if row is None:
                raise InteractionNotFound(interaction_id)
            if row["status"] != "pending":
                if row["decision"] == decision:
                    return _interaction(row)
                raise InteractionConflict("interaction has already been resolved")
            db.execute(
                """
                UPDATE interactions
                SET status='resolved',decision=?,decided_by=?,resolved_at=?
                WHERE id=? AND status='pending'
                """,
                (decision, actor[:300], now, interaction_id),
            )
            resolved = db.execute(
                "SELECT * FROM interactions WHERE id=?", (interaction_id,)
            ).fetchone()
        assert resolved is not None
        return _interaction(resolved)

    def expire_run(self, run_id: str) -> int:
        with self.store.connect() as db:
            return int(
                db.execute(
                    """
                    UPDATE interactions SET status='expired',resolved_at=?
                    WHERE run_id=? AND status='pending'
                    """,
                    (_now(), run_id),
                ).rowcount
            )

    def _migrate(self) -> None:
        with self.store.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS interactions(
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    bot_name TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('permission')),
                    request_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','resolved','expired')),
                    decision TEXT NOT NULL DEFAULT '',
                    decided_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    resolved_at TEXT NOT NULL DEFAULT '',
                    UNIQUE(run_id,request_id)
                );
                CREATE INDEX IF NOT EXISTS interactions_pending
                ON interactions(status,bot_name,created_at);
                """
            )


def _interaction(row: sqlite3.Row) -> Interaction:
    return Interaction(
        id=str(row["id"]),
        run_id=str(row["run_id"]),
        bot_name=str(row["bot_name"]),
        actor=str(row["actor"]),
        kind=str(row["kind"]),
        request_id=str(row["request_id"]),
        title=str(row["title"]),
        tool_name=str(row["tool_name"]),
        status=str(row["status"]),  # type: ignore[arg-type]
        decision=str(row["decision"]),
        decided_by=str(row["decided_by"]),
        created_at=str(row["created_at"]),
        resolved_at=str(row["resolved_at"]),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
