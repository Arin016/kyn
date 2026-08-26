"""Opt-in live smoke test for Scheduler -> Engine -> local Kiro ACP."""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from kyn.engine import Engine
from kyn.governance import GovernanceStore
from kyn.routines import RoutineStore, Scheduler
from kyn.store import Bot, Store


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="kyn-live-") as home:
        store = Store(home)
        store.put_bot(Bot(name="scheduled-smoke", cwd=str(Path.cwd())))
        governance = GovernanceStore(store)
        engine = Engine(store=store, governance=governance)
        routines = RoutineStore(store, min_interval_seconds=1)
        run_ids: list[str] = []

        async def submit(bot_name: str, prompt: str) -> str:
            run_id = await engine.submit(bot_name, prompt, actor="scheduler")
            run_ids.append(run_id)
            return run_id

        scheduler = Scheduler(routines, submit, poll_seconds=60)
        routines.create(
            name="Live ACP smoke",
            bot_name="scheduled-smoke",
            prompt="Reply with exactly SCHEDULED_KIRO_OK and nothing else.",
            trigger_kind="once",
            run_at=datetime.now(timezone.utc),
        )
        await engine.start()
        try:
            fired = await scheduler.tick()
            if fired != 1 or len(run_ids) != 1:
                raise RuntimeError("the due routine was not submitted exactly once")
            run_id = run_ids[0]
            while True:
                run = await engine.get_run(run_id)
                if run["status"] in {"complete", "failed", "cancelled"}:
                    break
                await asyncio.sleep(0.25)
            text = "".join(
                event["text"] for event in run["events"] if event["kind"] == "text"
            )
            if run["status"] != "complete" or "SCHEDULED_KIRO_OK" not in text:
                raise RuntimeError(
                    f"unexpected live result: {run['status']}: {text!r}; "
                    f"error={run['error']!r}; events={run['events']!r}"
                )
            audit = governance.list_audit(run_id=run_id)
            if {item["event_type"] for item in audit} != {
                "run_submission",
                "run_outcome",
            }:
                raise RuntimeError(f"unexpected audit trail: {audit!r}")
            print("SCHEDULED_KIRO_OK")
        finally:
            await engine.close()


if __name__ == "__main__":
    asyncio.run(main())
