from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from kyn.run_store import InvalidLease, RunConflict, RunRepository
from kyn.store import Bot, Store


NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


def _repository(tmp_path, *, retention: int = 5_000) -> RunRepository:
    store = Store(tmp_path)
    if store.get_bot("builder") is None:
        store.put_bot(Bot(name="builder", cwd=str(tmp_path)))
    return RunRepository(store, max_terminal_runs=retention)


def test_enqueue_is_durable_and_idempotent_but_conflicts_are_rejected(tmp_path) -> None:
    repository = _repository(tmp_path)
    first = repository.enqueue("run-1", "builder", "Build the feature", now=NOW)
    same = repository.enqueue("run-1", "builder", "Build the feature", now=NOW)
    assert first == same

    reopened = _repository(tmp_path)
    assert reopened.get("run-1") == first
    with pytest.raises(RunConflict):
        reopened.enqueue("run-1", "builder", "Different prompt", now=NOW)


def test_claim_is_atomic_across_connections(tmp_path) -> None:
    repository = _repository(tmp_path)
    repository.enqueue("run-1", "builder", "Do work", now=NOW)

    def claim(worker: str):
        separate = _repository(tmp_path)
        return separate.claim("run-1", worker, now=NOW)

    with ThreadPoolExecutor(max_workers=8) as executor:
        leases = list(executor.map(claim, [f"worker-{index}" for index in range(8)]))
    winners = [lease for lease in leases if lease is not None]
    assert len(winners) == 1
    assert winners[0].run.attempt == 1
    assert repository.get("run-1").status == "running"


def test_stale_lease_requeues_and_old_token_cannot_mutate(tmp_path) -> None:
    repository = _repository(tmp_path)
    repository.enqueue("run-1", "builder", "Do work", now=NOW)
    old = repository.claim("run-1", "worker-1", lease_seconds=10, now=NOW)
    assert old is not None
    assert repository.requeue_stale(NOW + timedelta(seconds=9)) == 0
    assert repository.requeue_stale(NOW + timedelta(seconds=10)) == 1

    replacement = repository.claim("run-1", "worker-2", now=NOW + timedelta(seconds=11))
    assert replacement is not None
    assert replacement.run.attempt == 2
    with pytest.raises(InvalidLease):
        repository.finish("run-1", old.token, "complete", now=NOW + timedelta(seconds=12))
    completed = repository.finish(
        "run-1", replacement.token, "complete", now=NOW + timedelta(seconds=12)
    )
    assert completed.status == "complete"
    assert completed.finished_at is not None


def test_expired_lease_cannot_finish_before_requeue(tmp_path) -> None:
    repository = _repository(tmp_path)
    repository.enqueue("run-1", "builder", "Do work", now=NOW)
    lease = repository.claim("run-1", "worker-1", lease_seconds=5, now=NOW)
    assert lease is not None
    with pytest.raises(InvalidLease, match="expired"):
        repository.finish("run-1", lease.token, "complete", now=NOW + timedelta(seconds=5))


def test_startup_recovery_requeues_nonterminal_work_only(tmp_path) -> None:
    before_crash = _repository(tmp_path)
    before_crash.enqueue("running", "builder", "Running", now=NOW)
    before_crash.enqueue("waiting", "builder", "Waiting", now=NOW)
    before_crash.enqueue("done", "builder", "Done", now=NOW)
    running = before_crash.claim("running", "old-daemon", lease_seconds=3600, now=NOW)
    waiting = before_crash.claim("waiting", "old-daemon", lease_seconds=3600, now=NOW)
    done = before_crash.claim("done", "old-daemon", lease_seconds=3600, now=NOW)
    assert running and waiting and done
    before_crash.mark_waiting_permission("waiting", waiting.token, now=NOW)
    before_crash.finish("done", done.token, "complete", now=NOW)

    restarted = _repository(tmp_path)
    assert restarted.recover_startup(NOW + timedelta(seconds=1)) == 2
    assert restarted.get("running").status == "queued"
    assert restarted.get("waiting").status == "queued"
    assert restarted.get("done").status == "complete"
    assert {run.run_id for run in restarted.list_runs(status="queued")} == {"running", "waiting"}


def test_lease_renewal_permission_state_and_terminal_guard(tmp_path) -> None:
    repository = _repository(tmp_path)
    repository.enqueue("run-1", "builder", "Do work", now=NOW)
    lease = repository.claim_next("worker-1", bot_name="builder", lease_seconds=5, now=NOW)
    assert lease is not None
    renewed = repository.renew_lease(
        "run-1", lease.token, lease_seconds=20, now=NOW + timedelta(seconds=4)
    )
    waiting = repository.mark_waiting_permission(
        "run-1", lease.token, now=NOW + timedelta(seconds=5)
    )
    assert waiting.status == "waiting_permission"
    assert renewed.expires_at > lease.expires_at
    assert repository.mark_running("run-1", lease.token, now=NOW + timedelta(seconds=6)).status == "running"
    assert repository.finish("run-1", lease.token, "failed", now=NOW + timedelta(seconds=7)).status == "failed"
    with pytest.raises(Exception):
        repository.finish("run-1", lease.token, "complete", now=NOW + timedelta(seconds=8))


def test_bounded_retention_never_prunes_live_work(tmp_path) -> None:
    repository = _repository(tmp_path, retention=2)
    for index in range(4):
        run_id = f"done-{index}"
        moment = NOW + timedelta(seconds=index)
        repository.enqueue(run_id, "builder", f"Message {index}", now=moment)
        lease = repository.claim(run_id, "worker", now=moment)
        assert lease is not None
        repository.finish(run_id, lease.token, "complete", now=moment)
    repository.enqueue("queued", "builder", "Still queued", now=NOW)

    assert repository.get("done-0") is None
    assert repository.get("done-1") is None
    assert repository.get("done-2") is not None
    assert repository.get("done-3") is not None
    assert repository.get("queued").status == "queued"


def test_schema_contains_message_but_no_event_or_secret_payloads(tmp_path) -> None:
    repository = _repository(tmp_path)
    repository.enqueue("run-1", "builder", "Only the user message", now=NOW)
    with repository.store.connect() as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(durable_runs)")}
        table_names = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'durable_run%'"
            )
        }
    assert "message" in columns
    assert columns.isdisjoint({"event_payload", "tool_input", "tool_arguments", "secret"})
    assert table_names == {"durable_runs"}


def test_keyset_pagination_covers_more_than_one_page(tmp_path) -> None:
    repository = _repository(tmp_path)
    for index in range(5):
        repository.enqueue(f"run-{index}", "builder", str(index), now=NOW)
    first = repository.list_runs(status="queued", limit=2)
    second = repository.list_runs(
        status="queued",
        limit=2,
        after_created_at=first[-1].created_at,
        after_run_id=first[-1].run_id,
    )
    third = repository.list_runs(
        status="queued",
        limit=2,
        after_created_at=second[-1].created_at,
        after_run_id=second[-1].run_id,
    )
    assert [run.run_id for run in first + second + third] == [
        "run-0", "run-1", "run-2", "run-3", "run-4"
    ]
