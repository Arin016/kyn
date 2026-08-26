from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from kyn.routines import RoutineStore, Scheduler
from kyn.store import Bot, Store


UTC = timezone.utc


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


def _service(tmp_path, *, minimum: int = 60) -> tuple[RoutineStore, MutableClock]:
    store = Store(tmp_path)
    store.put_bot(Bot(name="builder", cwd=str(tmp_path)))
    clock = MutableClock(datetime(2026, 8, 25, 12, 0, tzinfo=UTC))
    return RoutineStore(store, min_interval_seconds=minimum), clock


def test_routine_persists_across_service_instances(tmp_path) -> None:
    service, clock = _service(tmp_path)
    routine = service.create(
        name="morning brief",
        bot_name="builder",
        prompt="Summarize open work",
        trigger_kind="interval",
        interval_seconds=300,
        now=clock(),
    )

    reopened = RoutineStore(service.store)
    assert reopened.get(routine.id) == routine
    assert reopened.list(bot_name="builder") == [routine]


def test_validation_rejects_invalid_definitions(tmp_path) -> None:
    service, clock = _service(tmp_path)
    with pytest.raises(ValueError, match="routine name"):
        service.create(
            name=" ",
            bot_name="builder",
            prompt="work",
            trigger_kind="interval",
            interval_seconds=60,
            now=clock(),
        )
    with pytest.raises(ValueError, match="does not exist"):
        service.create(
            name="unknown bot",
            bot_name="missing",
            prompt="work",
            trigger_kind="interval",
            interval_seconds=60,
            now=clock(),
        )
    with pytest.raises(ValueError, match="at least 60"):
        service.create(
            name="too frequent",
            bot_name="builder",
            prompt="work",
            trigger_kind="interval",
            interval_seconds=59,
            now=clock(),
        )
    with pytest.raises(ValueError, match="timezone"):
        service.create(
            name="naive once",
            bot_name="builder",
            prompt="work",
            trigger_kind="once",
            run_at=datetime(2026, 8, 25, 13, 0),
            now=clock(),
        )


def test_claim_is_exclusive_across_concurrent_scheduler_owners(tmp_path) -> None:
    async def scenario() -> None:
        service, clock = _service(tmp_path)
        routine = service.create(
            name="due",
            bot_name="builder",
            prompt="work",
            trigger_kind="once",
            run_at=clock(),
            now=clock(),
        )

        first, second = await asyncio.gather(
            asyncio.to_thread(service.claim_due, "owner-a", now=clock()),
            asyncio.to_thread(service.claim_due, "owner-b", now=clock()),
        )
        claimed = first + second
        assert [item.id for item in claimed] == [routine.id]

    asyncio.run(scenario())


def test_interval_success_reschedules_from_completion_without_catch_up(tmp_path) -> None:
    async def scenario() -> None:
        service, clock = _service(tmp_path)
        routine = service.create(
            name="poll",
            bot_name="builder",
            prompt="work",
            trigger_kind="interval",
            interval_seconds=120,
            next_run_at=clock(),
            now=clock(),
        )
        calls: list[tuple[str, str]] = []

        async def submit(bot: str, prompt: str) -> None:
            calls.append((bot, prompt))
            clock.advance(600)

        scheduler = Scheduler(service, submit, clock=clock, owner="one")
        assert await scheduler.tick() == 1

        saved = service.get(routine.id)
        assert saved is not None
        assert calls == [("builder", "work")]
        assert saved.last_run_at == clock().isoformat()
        assert saved.next_run_at == (clock() + timedelta(seconds=120)).isoformat()
        assert service.due(now=clock()) == []

    asyncio.run(scenario())


def test_once_disables_only_after_successful_submission(tmp_path) -> None:
    async def scenario() -> None:
        service, clock = _service(tmp_path)
        routine = service.create(
            name="launch",
            bot_name="builder",
            prompt="launch once",
            trigger_kind="once",
            run_at=clock(),
            now=clock(),
        )

        async def submit(_bot: str, _prompt: str) -> str:
            return "run-id"

        scheduler = Scheduler(service, submit, clock=clock)
        await scheduler.tick()
        saved = service.get(routine.id)
        assert saved is not None
        assert saved.enabled is False
        assert saved.last_run_at == clock().isoformat()
        assert saved.next_run_at is None

    asyncio.run(scenario())


def test_failed_submission_is_released_and_retried_after_backoff(tmp_path) -> None:
    async def scenario() -> None:
        service, clock = _service(tmp_path)
        routine = service.create(
            name="retry",
            bot_name="builder",
            prompt="unstable",
            trigger_kind="once",
            run_at=clock(),
            now=clock(),
        )
        attempts = 0

        async def submit(_bot: str, _prompt: str) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary failure")

        scheduler = Scheduler(
            service,
            submit,
            clock=clock,
            retry_backoff_seconds=10,
            owner="retry-worker",
        )
        await scheduler.tick()
        failed = service.get(routine.id)
        assert failed is not None and failed.enabled
        assert failed.next_run_at == (clock() + timedelta(seconds=10)).isoformat()
        assert service.due(now=clock()) == []

        clock.advance(10)
        await scheduler.tick()
        completed = service.get(routine.id)
        assert attempts == 2
        assert completed is not None and not completed.enabled

    asyncio.run(scenario())


def test_scheduler_shutdown_wakes_poll_loop_and_is_idempotent(tmp_path) -> None:
    async def scenario() -> None:
        service, clock = _service(tmp_path)

        async def submit(_bot: str, _prompt: str) -> None:
            raise AssertionError("nothing is due")

        scheduler = Scheduler(service, submit, clock=clock, poll_seconds=60)
        await scheduler.start()
        await asyncio.wait_for(scheduler.close(), timeout=0.5)
        await scheduler.close()

    asyncio.run(scenario())


def test_timing_patch_recomputes_next_run_and_once_resume_is_actionable(tmp_path) -> None:
    service, clock = _service(tmp_path)
    routine = service.create(
        name="one shot",
        bot_name="builder",
        prompt="work",
        trigger_kind="once",
        run_at=clock(),
        now=clock(),
    )
    claimed = service.claim_due("worker", now=clock())
    assert claimed and service.mark_success(routine.id, "worker", now=clock())

    clock.advance(60)
    resumed = service.update(routine.id, enabled=True, now=clock())
    assert resumed.enabled
    assert resumed.next_run_at == clock().isoformat()
    assert [item.id for item in service.due(now=clock())] == [routine.id]

    moved = clock() + timedelta(hours=2)
    updated = service.update(routine.id, run_at=moved, now=clock())
    assert updated.run_at == moved.isoformat()
    assert updated.next_run_at == moved.isoformat()
