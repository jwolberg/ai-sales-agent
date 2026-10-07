"""Background-task tracking (ticket 0008): tasks are strongly referenced and crashes are logged."""

import asyncio
import logging

from app import tasks
from app.config import Settings


def test_spawned_task_is_tracked_until_done():
    async def scenario():
        gate = asyncio.Event()

        async def work():
            await gate.wait()

        task = tasks.spawn(work(), name="sim-call")
        assert task in tasks.running()
        gate.set()
        await task
        await asyncio.sleep(0)  # done-callbacks run on the next loop iteration
        assert task not in tasks.running()

    asyncio.run(scenario())


def test_crashing_task_is_logged_not_lost(caplog):
    async def scenario():
        async def boom():
            raise RuntimeError("persona script exploded")

        task = tasks.spawn(boom(), name="sim-call")
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

    with caplog.at_level(logging.ERROR, logger="app"):
        asyncio.run(scenario())
    records = [r for r in caplog.records if "sim-call" in r.getMessage()]
    assert records and records[0].exc_info and "exploded" in str(records[0].exc_info[1])


def test_cancelled_task_is_not_logged_as_error(caplog):
    async def scenario():
        task = tasks.spawn(asyncio.sleep(10), name="voice-call")
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

    with caplog.at_level(logging.ERROR, logger="app"):
        asyncio.run(scenario())
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_sim_start_spawns_a_tracked_task(monkeypatch):
    from app.dashboard import router as dash

    async def scenario():
        gate = asyncio.Event()

        async def fake_call(_persona):
            await gate.wait()

        monkeypatch.setattr(dash, "run_sim_call_paced", fake_call)
        monkeypatch.setattr(
            dash, "get_settings", lambda: Settings(_env_file=None, max_concurrent_sessions=3)
        )
        await dash.sim_start(dash.SimStartRequest())
        assert len(tasks.running()) == 1
        gate.set()
        for _ in range(5):
            await asyncio.sleep(0)
        assert tasks.running() == set()

    asyncio.run(scenario())
