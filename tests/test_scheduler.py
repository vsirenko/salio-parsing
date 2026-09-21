"""The clock, the lock and the subprocesses.

What the scheduler *decides* is not tested here — it is an ordinary query, covered in
tests/test_runs.py through `GET /api/admin/runs/due`. This is the part that only shows up
when a process is actually running: being the only one, sweeping what a dead one left, and
owing a finish to a worker that stopped answering.
"""

import sys

import pytest

from app.core.config import settings
from tests.test_auth import auth
from tests.test_matching import admin_token
from tests.test_offers import post
from tests.test_runs import channel, start

EXIT_BADLY = "/bin/sh -c 'exit 3'"
REAL_WORKER = f"{sys.executable} -m app.features.runs.worker --run-id {{run_id}}"


@pytest.fixture
def tuned():
    """Settings are one module-level object, so anything touched has to be put back."""
    kept = (settings.worker_command, settings.scheduler_max_running)
    yield settings
    settings.worker_command, settings.scheduler_max_running = kept


def scheduler():
    from app.features.runs.scheduler import Scheduler

    return Scheduler()


def runs_of(client, token) -> list[dict]:
    return client.get("/api/admin/runs", headers=auth(token)).json()["items"]


# --- being the only one ---


def test_a_second_scheduler_refuses_to_start(client, event_loop):
    """Two of them would each start the other's channels."""
    from app.features.runs.scheduler import Busy

    first, second = scheduler(), scheduler()

    async def attempt():
        await first.acquire()
        try:
            with pytest.raises(Busy):
                await second.acquire()
        finally:
            await first.release()
        # Released, so the next one in gets it.
        await second.acquire()
        await second.release()

    event_loop.run_until_complete(attempt())


# --- what a dead one left behind ---


def test_startup_closes_runs_nobody_is_working_on(client, event_loop, tuned):
    """Not a timeout: the scheduler is single, so a live row at its startup is a corpse."""
    token = admin_token(client)
    source = channel(client, token, cron_full=None, cron_quick=None)
    orphan = start(client, token, source["id"])

    tuned.worker_command = EXIT_BADLY
    event_loop.run_until_complete(scheduler().run_forever(once=True))

    closed = next(r for r in runs_of(client, token) if r["id"] == orphan["id"])
    assert closed["status"] == "interrupted"
    assert closed["finished_at"] is not None


# --- what it owes a worker ---


def test_a_worker_finishes_its_own_run(client, event_loop, tuned):
    """The real worker, spawned for real. It has no channel to collect, and says so."""
    token = admin_token(client)
    source = channel(client, token, cron_full="* * * * *", cron_quick=None)

    tuned.worker_command = REAL_WORKER
    event_loop.run_until_complete(scheduler().run_forever(once=True))

    runs = runs_of(client, token)
    assert len(runs) == 1
    assert runs[0]["source_id"] == source["id"]
    assert runs[0]["status"] == "failed"
    # Its own reason, not the scheduler's guess from an exit code.
    assert "no channel implementation" in runs[0]["error"]


def test_a_worker_that_dies_silently_still_closes_its_run(client, event_loop, tuned):
    """Otherwise a crashed worker holds that channel's live slot until the next restart."""
    token = admin_token(client)
    channel(client, token, cron_full="* * * * *", cron_quick=None)

    tuned.worker_command = EXIT_BADLY
    event_loop.run_until_complete(scheduler().run_forever(once=True))

    runs = runs_of(client, token)
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert "exited with 3" in runs[0]["error"]


# --- how much it starts ---


def test_it_starts_no_more_than_it_is_allowed(client, event_loop, tuned):
    """Two concurrent crawls on a small box is how the memory limit gets found."""
    token = admin_token(client)
    first = channel(client, token, slug="rd-one", cron_full="* * * * *", cron_quick=None)
    # A second channel into the same shop, which is the case the model is built around.
    post(
        client,
        token,
        f"/api/admin/shops/{first['shop_id']}/sources",
        {
            "slug": "rd-two",
            "access": "retail",
            "decode": "markup",
            "delivers_full": ["catalogue", "price", "availability"],
            "is_enabled": True,
            "cron_full": "* * * * *",
        },
    )

    tuned.worker_command = EXIT_BADLY
    tuned.scheduler_max_running = 1

    started = event_loop.run_until_complete(_one_tick())
    assert started == 1
    assert len(runs_of(client, token)) == 1


async def _one_tick() -> int:
    sched = scheduler()
    await sched.acquire()
    try:
        return await sched.tick()
    finally:
        # Left running on purpose: the point is that the second channel was not started.
        for worker in sched.workers.values():
            await worker.process.wait()
        await sched.release()
