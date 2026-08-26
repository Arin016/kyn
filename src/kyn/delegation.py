from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Literal, Mapping, Sequence

from .store import Store


PlanStatus = Literal[
    "paused", "pending", "running", "succeeded", "failed", "cancelled"
]
NodeStatus = Literal[
    "pending", "claimed", "running", "succeeded", "failed", "blocked", "cancelled"
]
Submit = Callable[[str, str], Awaitable[str]]
Wait = Callable[[str], Awaitable[Mapping[str, Any]]]
Cancel = Callable[[str], Awaitable[object]]

_NODE_TERMINAL = frozenset({"succeeded", "failed", "blocked", "cancelled"})
_PLAN_TERMINAL = frozenset({"succeeded", "failed", "cancelled"})


@dataclass(frozen=True, slots=True)
class NodeSpec:
    id: str
    bot_name: str
    prompt: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EdgeSpec:
    source: str
    target: str


@dataclass(frozen=True, slots=True)
class DelegationPlan:
    id: str
    name: str
    status: PlanStatus
    max_fanout: int
    max_depth: int
    aggregation_metadata: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class DelegationNode:
    id: str
    plan_id: str
    bot_name: str
    prompt: str
    status: NodeStatus
    depth: int
    ordinal: int
    run_id: str | None
    result: Any
    error: str
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class DelegationEdge:
    plan_id: str
    source: str
    target: str


class PlanNotFound(KeyError):
    pass


class NodeNotFound(KeyError):
    pass


class InvalidGraph(ValueError):
    pass


class DelegationStore:
    """SQLite-backed task graphs with recoverable, exclusive node claims."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self._migrate()

    def create_plan(
        self,
        *,
        name: str,
        nodes: Sequence[NodeSpec],
        edges: Sequence[EdgeSpec] = (),
        max_fanout: int = 4,
        max_depth: int = 4,
        plan_id: str | None = None,
        start: bool = True,
        now: str | datetime | None = None,
    ) -> DelegationPlan:
        timestamp = _iso(_utc(now))
        plan_id = (plan_id or uuid.uuid4().hex).strip()
        name = name.strip()
        if not plan_id:
            raise ValueError("plan id must not be blank")
        _validate_label(name, "plan name")
        if max_fanout < 1:
            raise ValueError("max_fanout must be at least 1")
        if max_depth < 0:
            raise ValueError("max_depth must not be negative")
        normalized_nodes, normalized_edges, depths = self._validate_graph(
            nodes, edges, max_fanout=max_fanout, max_depth=max_depth
        )
        visible_status = "pending" if start else "paused"
        empty_aggregation = _empty_aggregation(plan_id, visible_status)
        with self.store.connect() as db:
            db.execute("PRAGMA busy_timeout = 5000")
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """
                INSERT INTO delegation_plans(
                    id, name, status, max_fanout, max_depth,
                    aggregation_json, dispatch_state, created_at, updated_at
                ) VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    name,
                    int(max_fanout),
                    int(max_depth),
                    _json(empty_aggregation),
                    "active" if start else "paused",
                    timestamp,
                    timestamp,
                ),
            )
            for ordinal, node in enumerate(normalized_nodes):
                db.execute(
                    """
                    INSERT INTO delegation_nodes(
                        id, plan_id, bot_name, prompt, status, depth, ordinal,
                        run_id, result_json, error, metadata_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'pending', ?, ?, NULL, NULL, '', ?, ?, ?)
                    """,
                    (
                        node.id,
                        plan_id,
                        node.bot_name,
                        node.prompt,
                        depths[node.id],
                        ordinal,
                        _json(node.metadata),
                        timestamp,
                        timestamp,
                    ),
                )
            db.executemany(
                "INSERT INTO delegation_edges(plan_id, source, target) VALUES (?, ?, ?)",
                [(plan_id, edge.source, edge.target) for edge in normalized_edges],
            )
            self._refresh_plan(db, plan_id, timestamp)
        plan = self.get_plan(plan_id)
        assert plan is not None
        return plan

    def get_plan(self, plan_id: str) -> DelegationPlan | None:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM delegation_plans WHERE id = ?", (plan_id,)
            ).fetchone()
        return _plan(row) if row is not None else None

    def list_plans(self, *, status: PlanStatus | None = None) -> list[DelegationPlan]:
        with self.store.connect() as db:
            if status is None:
                rows = db.execute(
                    "SELECT * FROM delegation_plans ORDER BY created_at, id"
                ).fetchall()
            elif status == "paused":
                rows = db.execute(
                    "SELECT * FROM delegation_plans WHERE dispatch_state = 'paused' "
                    "AND status IN ('pending', 'running') ORDER BY created_at, id"
                ).fetchall()
            elif status == "pending":
                rows = db.execute(
                    "SELECT * FROM delegation_plans WHERE status = 'pending' "
                    "AND dispatch_state = 'active' ORDER BY created_at, id"
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM delegation_plans WHERE status = ? "
                    "ORDER BY created_at, id",
                    (status,),
                ).fetchall()
        return [_plan(row) for row in rows]

    def get_node(self, plan_id: str, node_id: str) -> DelegationNode | None:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM delegation_nodes WHERE plan_id = ? AND id = ?",
                (plan_id, node_id),
            ).fetchone()
        return _node(row) if row is not None else None

    def nodes(self, plan_id: str) -> list[DelegationNode]:
        self._require_plan(plan_id)
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT * FROM delegation_nodes WHERE plan_id = ? "
                "ORDER BY depth, ordinal, id",
                (plan_id,),
            ).fetchall()
        return [_node(row) for row in rows]

    def edges(self, plan_id: str) -> list[DelegationEdge]:
        self._require_plan(plan_id)
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT * FROM delegation_edges WHERE plan_id = ? "
                "ORDER BY source, target",
                (plan_id,),
            ).fetchall()
        return [
            DelegationEdge(plan_id=row["plan_id"], source=row["source"], target=row["target"])
            for row in rows
        ]

    def delete_plan(self, plan_id: str) -> bool:
        with self.store.connect() as db:
            cursor = db.execute("DELETE FROM delegation_plans WHERE id = ?", (plan_id,))
        return cursor.rowcount == 1

    def start_plan(
        self, plan_id: str, *, now: str | datetime | None = None
    ) -> DelegationPlan:
        timestamp = _iso(_utc(now))
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status, dispatch_state FROM delegation_plans WHERE id = ?",
                (plan_id,),
            ).fetchone()
            if row is None:
                raise PlanNotFound(plan_id)
            if row["status"] in _PLAN_TERMINAL:
                raise ValueError("a terminal delegation plan cannot be started")
            db.execute(
                "UPDATE delegation_plans SET dispatch_state = 'active', updated_at = ? "
                "WHERE id = ?",
                (timestamp, plan_id),
            )
            self._refresh_plan(db, plan_id, timestamp)
        plan = self.get_plan(plan_id)
        assert plan is not None
        return plan

    def claim_ready(
        self,
        owner: str,
        *,
        plan_id: str | None = None,
        limit: int = 4,
        lease_seconds: float = 300,
        now: str | datetime | None = None,
    ) -> list[DelegationNode]:
        owner = owner.strip()
        if not owner:
            raise ValueError("lease owner must not be blank")
        if limit < 1:
            return []
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        current = _utc(now)
        timestamp = _iso(current)
        lease_until = _iso(current + timedelta(seconds=lease_seconds))
        plan_filter = " AND n.plan_id = ?" if plan_id is not None else ""
        parameters: list[object] = [timestamp]
        if plan_id is not None:
            parameters.append(plan_id)
        parameters.append(int(limit))
        with self.store.connect() as db:
            db.execute("PRAGMA busy_timeout = 5000")
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                f"""
                SELECT n.* FROM delegation_nodes n
                JOIN delegation_plans p ON p.id = n.plan_id
                WHERE p.status IN ('pending', 'running')
                  AND p.dispatch_state = 'active'
                  AND (
                    (
                      n.status = 'pending'
                      AND NOT EXISTS (
                        SELECT 1 FROM delegation_edges e
                        JOIN delegation_nodes parent
                          ON parent.plan_id = e.plan_id AND parent.id = e.source
                        WHERE e.plan_id = n.plan_id AND e.target = n.id
                          AND parent.status != 'succeeded'
                      )
                    )
                    OR (
                      n.status IN ('claimed', 'running')
                      AND n.lease_until IS NOT NULL AND n.lease_until <= ?
                    )
                  )
                  {plan_filter}
                ORDER BY n.depth, n.ordinal, n.id
                LIMIT ?
                """,
                parameters,
            ).fetchall()
            claimed: list[DelegationNode] = []
            touched_plans: set[str] = set()
            for row in rows:
                next_status = "claimed" if row["status"] != "running" else "running"
                cursor = db.execute(
                    """
                    UPDATE delegation_nodes
                    SET status = ?, lease_owner = ?, lease_until = ?, updated_at = ?
                    WHERE plan_id = ? AND id = ?
                      AND status IN ('pending', 'claimed', 'running')
                      AND (lease_until IS NULL OR lease_until <= ?)
                    """,
                    (
                        next_status,
                        owner,
                        lease_until,
                        timestamp,
                        row["plan_id"],
                        row["id"],
                        timestamp,
                    ),
                )
                if cursor.rowcount == 1:
                    fresh = db.execute(
                        "SELECT * FROM delegation_nodes WHERE plan_id = ? AND id = ?",
                        (row["plan_id"], row["id"]),
                    ).fetchone()
                    claimed.append(_node(fresh))
                    touched_plans.add(row["plan_id"])
            for touched in touched_plans:
                self._refresh_plan(db, touched, timestamp)
        return claimed

    def mark_running(
        self,
        plan_id: str,
        node_id: str,
        owner: str,
        run_id: str,
        *,
        now: str | datetime | None = None,
    ) -> bool:
        if not run_id or not run_id.strip():
            raise ValueError("run_id must not be blank")
        timestamp = _iso(_utc(now))
        with self.store.connect() as db:
            cursor = db.execute(
                """
                UPDATE delegation_nodes
                SET status = 'running', run_id = ?, updated_at = ?
                WHERE plan_id = ? AND id = ? AND status = 'claimed' AND lease_owner = ?
                """,
                (run_id.strip(), timestamp, plan_id, node_id, owner),
            )
        return cursor.rowcount == 1

    def renew_claim(
        self,
        plan_id: str,
        node_id: str,
        owner: str,
        *,
        lease_seconds: float = 300,
        now: str | datetime | None = None,
    ) -> bool:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        current = _utc(now)
        timestamp = _iso(current)
        lease_until = _iso(current + timedelta(seconds=lease_seconds))
        with self.store.connect() as db:
            cursor = db.execute(
                """
                UPDATE delegation_nodes
                SET lease_until = ?, updated_at = ?
                WHERE plan_id = ? AND id = ? AND lease_owner = ?
                  AND status IN ('claimed', 'running')
                """,
                (lease_until, timestamp, plan_id, node_id, owner),
            )
        return cursor.rowcount == 1

    def release_claim(
        self,
        plan_id: str,
        node_id: str,
        owner: str,
        *,
        now: str | datetime | None = None,
    ) -> bool:
        """Make an interrupted node immediately recoverable by another tick."""
        timestamp = _iso(_utc(now))
        with self.store.connect() as db:
            cursor = db.execute(
                """
                UPDATE delegation_nodes
                SET status = CASE WHEN run_id IS NULL THEN 'pending' ELSE 'running' END,
                    lease_owner = NULL,
                    lease_until = CASE WHEN run_id IS NULL THEN NULL ELSE ? END,
                    updated_at = ?
                WHERE plan_id = ? AND id = ? AND lease_owner = ?
                  AND status IN ('claimed', 'running')
                """,
                (timestamp, timestamp, plan_id, node_id, owner),
            )
            if cursor.rowcount == 1:
                self._refresh_plan(db, plan_id, timestamp)
        return cursor.rowcount == 1

    def mark_success(
        self,
        plan_id: str,
        node_id: str,
        owner: str,
        result: Any,
        *,
        now: str | datetime | None = None,
    ) -> bool:
        return self._finish_node(
            plan_id, node_id, owner, "succeeded", result=result, now=now
        )

    def mark_failure(
        self,
        plan_id: str,
        node_id: str,
        owner: str,
        error: str,
        *,
        now: str | datetime | None = None,
    ) -> bool:
        return self._finish_node(
            plan_id, node_id, owner, "failed", error=error, now=now
        )

    def cancel_plan(
        self, plan_id: str, *, now: str | datetime | None = None
    ) -> list[str]:
        timestamp = _iso(_utc(now))
        with self.store.connect() as db:
            db.execute("PRAGMA busy_timeout = 5000")
            db.execute("BEGIN IMMEDIATE")
            plan = db.execute(
                "SELECT status FROM delegation_plans WHERE id = ?", (plan_id,)
            ).fetchone()
            if plan is None:
                raise PlanNotFound(plan_id)
            if plan["status"] in _PLAN_TERMINAL:
                return []
            rows = db.execute(
                "SELECT run_id FROM delegation_nodes "
                "WHERE plan_id = ? AND status = 'running' AND run_id IS NOT NULL "
                "ORDER BY depth, ordinal, id",
                (plan_id,),
            ).fetchall()
            run_ids = [row["run_id"] for row in rows]
            db.execute(
                """
                UPDATE delegation_nodes
                SET status = 'cancelled', lease_owner = NULL, lease_until = NULL,
                    updated_at = ?
                WHERE plan_id = ? AND status NOT IN ('succeeded', 'failed', 'blocked', 'cancelled')
                """,
                (timestamp, plan_id),
            )
            db.execute(
                "UPDATE delegation_plans SET status = 'cancelled', dispatch_state = 'active', "
                "updated_at = ? WHERE id = ?",
                (timestamp, plan_id),
            )
            self._write_aggregation(db, plan_id, timestamp)
        return run_ids

    def aggregation(self, plan_id: str) -> dict[str, Any]:
        self._require_plan(plan_id)
        with self.store.connect() as db:
            return self._build_aggregation(db, plan_id)

    def _finish_node(
        self,
        plan_id: str,
        node_id: str,
        owner: str,
        status: Literal["succeeded", "failed"],
        *,
        result: Any = None,
        error: str = "",
        now: str | datetime | None,
    ) -> bool:
        timestamp = _iso(_utc(now))
        with self.store.connect() as db:
            db.execute("PRAGMA busy_timeout = 5000")
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                """
                UPDATE delegation_nodes
                SET status = ?, result_json = ?, error = ?,
                    lease_owner = NULL, lease_until = NULL, updated_at = ?
                WHERE plan_id = ? AND id = ?
                  AND status IN ('claimed', 'running') AND lease_owner = ?
                """,
                (
                    status,
                    _json(_json_safe(result)) if status == "succeeded" else None,
                    str(error).strip() if status == "failed" else "",
                    timestamp,
                    plan_id,
                    node_id,
                    owner,
                ),
            )
            if cursor.rowcount != 1:
                return False
            if status == "failed":
                # A failed dependency makes every transitive dependent
                # unreachable. Independent branches remain eligible to finish.
                db.execute(
                    """
                    WITH RECURSIVE descendants(id) AS (
                        SELECT target FROM delegation_edges
                        WHERE plan_id = ? AND source = ?
                        UNION
                        SELECT e.target FROM delegation_edges e
                        JOIN descendants d ON e.source = d.id
                        WHERE e.plan_id = ?
                    )
                    UPDATE delegation_nodes
                    SET status = 'blocked',
                        error = ?, lease_owner = NULL, lease_until = NULL,
                        updated_at = ?
                    WHERE plan_id = ? AND id IN (SELECT id FROM descendants)
                      AND status IN ('pending', 'claimed')
                    """,
                    (
                        plan_id,
                        node_id,
                        plan_id,
                        f"blocked by failed dependency {node_id}",
                        timestamp,
                        plan_id,
                    ),
                )
            self._refresh_plan(db, plan_id, timestamp)
        return True

    def _refresh_plan(self, db: sqlite3.Connection, plan_id: str, timestamp: str) -> None:
        rows = db.execute(
            "SELECT status, COUNT(*) AS count FROM delegation_nodes "
            "WHERE plan_id = ? GROUP BY status",
            (plan_id,),
        ).fetchall()
        counts = {row["status"]: int(row["count"]) for row in rows}
        nonterminal = sum(
            count for status, count in counts.items() if status not in _NODE_TERMINAL
        )
        if nonterminal:
            status = (
                "pending"
                if counts.get("pending", 0) == sum(counts.values())
                else "running"
            )
        elif counts.get("failed", 0) or counts.get("blocked", 0):
            status = "failed"
        elif counts.get("cancelled", 0):
            status = "cancelled"
        else:
            status = "succeeded"
        db.execute(
            "UPDATE delegation_plans SET status = ?, updated_at = ? WHERE id = ?",
            (status, timestamp, plan_id),
        )
        self._write_aggregation(db, plan_id, timestamp)

    def _write_aggregation(
        self, db: sqlite3.Connection, plan_id: str, timestamp: str
    ) -> None:
        aggregation = self._build_aggregation(db, plan_id)
        db.execute(
            "UPDATE delegation_plans SET aggregation_json = ?, updated_at = ? WHERE id = ?",
            (_json(aggregation), timestamp, plan_id),
        )

    def _build_aggregation(
        self, db: sqlite3.Connection, plan_id: str
    ) -> dict[str, Any]:
        plan = db.execute(
            "SELECT status, dispatch_state FROM delegation_plans WHERE id = ?", (plan_id,)
        ).fetchone()
        if plan is None:
            raise PlanNotFound(plan_id)
        rows = db.execute(
            "SELECT * FROM delegation_nodes WHERE plan_id = ? "
            "ORDER BY depth, ordinal, id",
            (plan_id,),
        ).fetchall()
        status_order = (
            "pending",
            "claimed",
            "running",
            "succeeded",
            "failed",
            "blocked",
            "cancelled",
        )
        counts = {status: 0 for status in status_order}
        items: list[dict[str, Any]] = []
        for row in rows:
            counts[row["status"]] += 1
            items.append(
                {
                    "node_id": row["id"],
                    "bot_name": row["bot_name"],
                    "status": row["status"],
                    "depth": int(row["depth"]),
                    "ordinal": int(row["ordinal"]),
                    "run_id": row["run_id"],
                    "result": _loads(row["result_json"], None),
                    "error": row["error"],
                    "metadata": _loads(row["metadata_json"], {}),
                }
            )
        return {
            "version": 1,
            "plan_id": plan_id,
            "status": (
                "paused"
                if plan["dispatch_state"] == "paused"
                and plan["status"] not in _PLAN_TERMINAL
                else plan["status"]
            ),
            "counts": counts,
            "nodes": items,
        }

    def _validate_graph(
        self,
        nodes: Sequence[NodeSpec],
        edges: Sequence[EdgeSpec],
        *,
        max_fanout: int,
        max_depth: int,
    ) -> tuple[list[NodeSpec], list[EdgeSpec], dict[str, int]]:
        if not nodes:
            raise InvalidGraph("a delegation plan requires at least one node")
        by_id: dict[str, NodeSpec] = {}
        normalized_nodes: list[NodeSpec] = []
        for node in nodes:
            node_id = node.id.strip()
            bot_name = node.bot_name.strip()
            prompt = node.prompt.strip()
            _validate_label(node_id, "node id")
            _validate_label(bot_name, "bot name")
            if not prompt:
                raise InvalidGraph(f"node {node_id!r} has a blank prompt")
            if node_id in by_id:
                raise InvalidGraph(f"duplicate node id {node_id!r}")
            if self.store.get_bot(bot_name) is None:
                raise InvalidGraph(f"bot {bot_name!r} does not exist")
            normalized = NodeSpec(
                id=node_id,
                bot_name=bot_name,
                prompt=prompt,
                metadata=_json_safe(node.metadata),
            )
            by_id[node_id] = normalized
            normalized_nodes.append(normalized)

        normalized_edges: list[EdgeSpec] = []
        seen_edges: set[tuple[str, str]] = set()
        outgoing = {node_id: [] for node_id in by_id}
        indegree = {node_id: 0 for node_id in by_id}
        for edge in edges:
            source, target = edge.source.strip(), edge.target.strip()
            if source not in by_id or target not in by_id:
                raise InvalidGraph(f"edge {source!r}->{target!r} references an unknown node")
            if source == target:
                raise InvalidGraph(f"node {source!r} cannot depend on itself")
            pair = (source, target)
            if pair in seen_edges:
                raise InvalidGraph(f"duplicate edge {source!r}->{target!r}")
            seen_edges.add(pair)
            outgoing[source].append(target)
            indegree[target] += 1
            normalized_edges.append(EdgeSpec(source, target))
        for source, targets in outgoing.items():
            if len(targets) > max_fanout:
                raise InvalidGraph(
                    f"node {source!r} fanout {len(targets)} exceeds limit {max_fanout}"
                )

        # Kahn traversal simultaneously proves acyclicity and computes longest
        # dependency depth. Input order is the stable tie-breaker.
        order = {node.id: index for index, node in enumerate(normalized_nodes)}
        ready = sorted((node_id for node_id, degree in indegree.items() if degree == 0), key=order.get)
        depths = {node_id: 0 for node_id in by_id}
        visited = 0
        while ready:
            node_id = ready.pop(0)
            visited += 1
            for target in sorted(outgoing[node_id], key=order.get):
                depths[target] = max(depths[target], depths[node_id] + 1)
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)
                    ready.sort(key=order.get)
        if visited != len(by_id):
            raise InvalidGraph("delegation graph contains a cycle")
        actual_depth = max(depths.values(), default=0)
        if actual_depth > max_depth:
            raise InvalidGraph(
                f"graph depth {actual_depth} exceeds limit {max_depth}"
            )
        return normalized_nodes, normalized_edges, depths

    def _require_plan(self, plan_id: str) -> None:
        if self.get_plan(plan_id) is None:
            raise PlanNotFound(plan_id)

    def _migrate(self) -> None:
        with self.store.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS delegation_plans (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'pending', 'running', 'succeeded', 'failed', 'cancelled'
                    )),
                    max_fanout INTEGER NOT NULL,
                    max_depth INTEGER NOT NULL,
                    aggregation_json TEXT NOT NULL DEFAULT '{}',
                    dispatch_state TEXT NOT NULL DEFAULT 'active'
                        CHECK(dispatch_state IN ('active', 'paused')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS delegation_nodes (
                    id TEXT NOT NULL,
                    plan_id TEXT NOT NULL REFERENCES delegation_plans(id) ON DELETE CASCADE,
                    bot_name TEXT NOT NULL REFERENCES bots(name) ON DELETE RESTRICT,
                    prompt TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'pending', 'claimed', 'running', 'succeeded',
                        'failed', 'blocked', 'cancelled'
                    )),
                    depth INTEGER NOT NULL,
                    ordinal INTEGER NOT NULL,
                    run_id TEXT,
                    result_json TEXT,
                    error TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    lease_owner TEXT,
                    lease_until TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(plan_id, id)
                );
                CREATE TABLE IF NOT EXISTS delegation_edges (
                    plan_id TEXT NOT NULL REFERENCES delegation_plans(id) ON DELETE CASCADE,
                    source TEXT NOT NULL,
                    target TEXT NOT NULL,
                    PRIMARY KEY(plan_id, source, target),
                    FOREIGN KEY(plan_id, source) REFERENCES delegation_nodes(plan_id, id) ON DELETE CASCADE,
                    FOREIGN KEY(plan_id, target) REFERENCES delegation_nodes(plan_id, id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_delegation_claim
                    ON delegation_nodes(status, lease_until, depth, ordinal);
                CREATE INDEX IF NOT EXISTS idx_delegation_edges_target
                    ON delegation_edges(plan_id, target);
                """
            )
            columns = {
                row["name"]
                for row in db.execute("PRAGMA table_info(delegation_plans)").fetchall()
            }
            if "dispatch_state" not in columns:
                db.execute(
                    "ALTER TABLE delegation_plans ADD COLUMN dispatch_state TEXT "
                    "NOT NULL DEFAULT 'active' CHECK(dispatch_state IN ('active', 'paused'))"
                )


class DelegationCoordinator:
    """Execute a durable graph through injected run submission/wait callbacks."""

    def __init__(
        self,
        service: DelegationStore,
        submit: Submit,
        wait: Wait,
        *,
        cancel: Cancel | None = None,
        max_concurrency: int = 4,
        lease_seconds: float = 300,
        owner: str | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self.service = service
        self.submit = submit
        self.wait = wait
        self.cancel = cancel
        self.max_concurrency = int(max_concurrency)
        self.lease_seconds = float(lease_seconds)
        self.owner = owner or f"delegator-{uuid.uuid4().hex}"
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._capacity = asyncio.Semaphore(self.max_concurrency)
        self._plan_locks: dict[str, asyncio.Lock] = {}
        self._active: set[asyncio.Task[None]] = set()
        self._closed = False

    async def tick(self, plan_id: str | None = None) -> int:
        if self._closed:
            return 0
        lock_key = plan_id or "*"
        lock = self._plan_locks.setdefault(lock_key, asyncio.Lock())
        async with lock:
            tasks: list[asyncio.Task[None]] = []
            for _ in range(self.max_concurrency):
                await self._capacity.acquire()
                if self._closed:
                    self._capacity.release()
                    break
                claimed = self.service.claim_ready(
                    self.owner,
                    plan_id=plan_id,
                    limit=1,
                    lease_seconds=self.lease_seconds,
                    now=self.clock(),
                )
                if not claimed:
                    self._capacity.release()
                    break
                task = asyncio.create_task(
                    self._execute_with_capacity(claimed[0]),
                    name=f"kyn-delegated-node:{claimed[0].plan_id}:{claimed[0].id}",
                )
                self._active.add(task)
                task.add_done_callback(self._active.discard)
                tasks.append(task)
            if tasks:
                await asyncio.gather(*tasks)
            return len(tasks)

    async def run_until_terminal(
        self, plan_id: str, *, poll_seconds: float = 0.05
    ) -> DelegationPlan:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        while True:
            plan = self.service.get_plan(plan_id)
            if plan is None:
                raise PlanNotFound(plan_id)
            if plan.status in _PLAN_TERMINAL:
                return plan
            claimed = await self.tick(plan_id)
            if claimed == 0:
                await asyncio.sleep(poll_seconds)

    async def cancel_plan(self, plan_id: str) -> DelegationPlan:
        run_ids = self.service.cancel_plan(plan_id, now=self.clock())
        if self.cancel is not None:
            await asyncio.gather(
                *(self.cancel(run_id) for run_id in run_ids), return_exceptions=True
            )
        plan = self.service.get_plan(plan_id)
        assert plan is not None
        return plan

    async def close(self) -> None:
        self._closed = True
        active = tuple(self._active)
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)

    async def _execute_with_capacity(self, node: DelegationNode) -> None:
        try:
            await self._execute(node)
        finally:
            self._capacity.release()

    async def _execute(self, node: DelegationNode) -> None:
        submit_task: asyncio.Task[str] | None = None
        try:
            run_id = node.run_id
            if node.status != "running" or not run_id:
                # Shield submission long enough to persist the returned run ID.
                # This closes the graceful-shutdown gap where accepted work was
                # previously forgotten and then submitted twice after restart.
                submit_task = asyncio.create_task(
                    self.submit(node.bot_name, node.prompt),
                    name=f"kyn-delegated-submit:{node.plan_id}:{node.id}",
                )
                try:
                    run_id = await asyncio.shield(submit_task)
                except asyncio.CancelledError:
                    try:
                        run_id = await submit_task
                    except Exception:
                        self.service.release_claim(
                            node.plan_id, node.id, self.owner, now=self.clock()
                        )
                        raise
                    self.service.mark_running(
                        node.plan_id,
                        node.id,
                        self.owner,
                        run_id,
                        now=self.clock(),
                    )
                    self.service.release_claim(
                        node.plan_id, node.id, self.owner, now=self.clock()
                    )
                    raise
                if not self.service.mark_running(
                    node.plan_id,
                    node.id,
                    self.owner,
                    run_id,
                    now=self.clock(),
                ):
                    return
            snapshot = await self._wait_with_lease(node, run_id)
            status = str(snapshot.get("status", "")).lower()
            if status in {"complete", "completed", "success", "succeeded"}:
                self.service.mark_success(
                    node.plan_id,
                    node.id,
                    self.owner,
                    snapshot,
                    now=self.clock(),
                )
            elif status == "cancelled":
                self.service.mark_failure(
                    node.plan_id,
                    node.id,
                    self.owner,
                    "delegated run was cancelled",
                    now=self.clock(),
                )
            else:
                detail = str(snapshot.get("error") or snapshot.get("stop_reason") or status)
                self.service.mark_failure(
                    node.plan_id,
                    node.id,
                    self.owner,
                    detail or "delegated run failed",
                    now=self.clock(),
                )
        except asyncio.CancelledError:
            self.service.release_claim(
                node.plan_id, node.id, self.owner, now=self.clock()
            )
            raise
        except Exception as exc:
            self.service.mark_failure(
                node.plan_id,
                node.id,
                self.owner,
                _error(exc),
                now=self.clock(),
            )

    async def _wait_with_lease(
        self, node: DelegationNode, run_id: str
    ) -> Mapping[str, Any]:
        wait_task = asyncio.create_task(
            self.wait(run_id),
            name=f"kyn-delegated-wait:{node.plan_id}:{node.id}",
        )
        heartbeat = max(min(self.lease_seconds / 3, 30), 0.05)
        try:
            while True:
                done, _ = await asyncio.wait(
                    {wait_task}, timeout=heartbeat, return_when=asyncio.FIRST_COMPLETED
                )
                if done:
                    return wait_task.result()
                if not self.service.renew_claim(
                    node.plan_id,
                    node.id,
                    self.owner,
                    lease_seconds=self.lease_seconds,
                    now=self.clock(),
                ):
                    raise RuntimeError("delegation node lease was lost")
        finally:
            if not wait_task.done():
                wait_task.cancel()
                await asyncio.gather(wait_task, return_exceptions=True)


def _plan(row: sqlite3.Row) -> DelegationPlan:
    status = row["status"]
    if row["dispatch_state"] == "paused" and status not in _PLAN_TERMINAL:
        status = "paused"
    return DelegationPlan(
        id=row["id"],
        name=row["name"],
        status=status,
        max_fanout=int(row["max_fanout"]),
        max_depth=int(row["max_depth"]),
        aggregation_metadata=_loads(row["aggregation_json"], {}),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _node(row: sqlite3.Row) -> DelegationNode:
    return DelegationNode(
        id=row["id"],
        plan_id=row["plan_id"],
        bot_name=row["bot_name"],
        prompt=row["prompt"],
        status=row["status"],
        depth=int(row["depth"]),
        ordinal=int(row["ordinal"]),
        run_id=row["run_id"],
        result=_loads(row["result_json"], None),
        error=row["error"],
        metadata=_loads(row["metadata_json"], {}),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _empty_aggregation(plan_id: str, status: str) -> dict[str, Any]:
    return {
        "version": 1,
        "plan_id": plan_id,
        "status": status,
        "counts": {
            name: 0
            for name in (
                "pending",
                "claimed",
                "running",
                "succeeded",
                "failed",
                "blocked",
                "cancelled",
            )
        },
        "nodes": [],
    }


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
    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(value, str)
        else value
    )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loads(value: str | None, default: Any) -> Any:
    return default if value is None else json.loads(value)


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def _error(exc: BaseException) -> str:
    detail = str(exc).strip()
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
