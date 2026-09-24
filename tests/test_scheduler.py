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
# A worker that closes its own run, without being the real one. The real worker reaches
# the service over HTTP, and a subprocess here would aim at whatever is listening on the
# configured port — in practice the development API, against the development database.
# The genuine article is exercised in tests/test_worker.py, in-process and against this
# app.
SELF_CLOSING = (
    f"{sys.executable} -c "
    "'import asyncio,os,sys;"
    'sys.path.insert(0,".");'
    "from app.db.session import session_factory;"
    "from app.features.runs.service import RunService;"
    "from app.features.runs.schemas import RunResult;"
    'asyncio.run(__import__("tests.helpers_worker",fromlist=["x"]).close(int(os.environ["RUN_ID"])))\''
)


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
    orphan = event_loop.run_until_complete(_running(source["id"]))

    tuned.worker_command = EXIT_BADLY
    event_loop.run_until_complete(scheduler().run_forever(once=True))

    closed = next(r for r in runs_of(client, token) if r["id"] == orphan)
    assert closed["status"] == "interrupted"
    assert closed["finished_at"] is not None


def test_a_run_asked_for_by_hand_waits_and_is_taken_on_the_next_tick(client, event_loop, tuned):
    """It used to be created running with no worker, and sat there until a startup swept
    it. Queued now: the sweep leaves it, and the tick gives it a worker before anything
    scheduled."""
    token = admin_token(client)
    source = channel(client, token, cron_full=None, cron_quick=None)
    asked = start(client, token, source["id"])
    assert asked["status"] == "queued"
    status = client.get("/api/admin/scheduler", headers=auth(token)).json()
    assert [r["id"] for r in status["queued"]] == [asked["id"]]

    tuned.worker_command = SELF_CLOSING
    event_loop.run_until_complete(_one_tick_waiting())

    taken = next(r for r in runs_of(client, token) if r["id"] == asked["id"])
    # Closed by the worker the tick spawned, with that worker's own verdict.
    assert taken["error"] == "reported by the worker", taken


# --- what it owes a worker ---


def test_a_worker_that_reported_keeps_its_own_verdict(client, event_loop, tuned):
    """The scheduler closes a run only when the process is gone and the row is still open."""
    token = admin_token(client)
    source = channel(client, token, cron_full="* * * * *", cron_quick=None)

    tuned.worker_command = SELF_CLOSING
    event_loop.run_until_complete(scheduler().run_forever(once=True))

    runs = runs_of(client, token)
    assert len(runs) == 1
    assert runs[0]["source_id"] == source["id"]
    assert runs[0]["status"] == "failed"
    # Its own reason, not the scheduler's guess from an exit code.
    assert runs[0]["error"] == "reported by the worker"


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


# --- saying it is alive ---


def test_a_tick_leaves_a_heartbeat_the_panel_and_the_container_can_read(client, event_loop):
    """With nothing due a working scheduler is as quiet as a stopped one; the heartbeat is
    what tells them apart — for `GET /scheduler` and for the container's own check."""
    from app.features.runs.scheduler import healthy

    token = admin_token(client)
    source = channel(client, token)
    before = client.get("/api/admin/scheduler", headers=auth(token)).json()
    assert before["alive"] is False
    assert event_loop.run_until_complete(healthy()) == 1

    event_loop.run_until_complete(scheduler().run_forever(once=True))

    after = client.get("/api/admin/scheduler", headers=auth(token)).json()
    assert after["alive"] is True
    assert after["ticked_at"] is not None
    assert event_loop.run_until_complete(healthy()) == 0
    # Every channel with its schedule and its next slot, computed from the cron.
    (row,) = [c for c in after["channels"] if c["source_id"] == source["id"]]
    assert row["cron_full"] == "0 3 * * *"
    assert row["next_full_at"] is not None and row["next_quick_at"] is not None


async def _running(source_id: int) -> int:
    """A run left running with no process behind it, the way a killed scheduler leaves one."""
    from app.db.session import session_factory
    from app.features.runs.schemas import Kind
    from app.features.runs.service import RunService

    async with session_factory() as session:
        run = await RunService(session).start(source_id, Kind.FULL)
        await session.commit()
        return run.id


async def _one_tick_waiting() -> None:
    """One whole scheduler pass, waiting for the worker it started to report."""
    sched = scheduler()
    await sched.acquire()
    try:
        await sched.tick()
        for worker in list(sched.workers.values()):
            await worker.process.wait()
        await sched.reap()
    finally:
        await sched.release()


def test_a_channel_says_whether_it_has_a_cheap_pass(client):
    """A panel offers a quick run only where there is one to run."""
    token = admin_token(client)
    with_quick = channel(client, token, slug="rd-site")
    without = post(
        client,
        token,
        f"/api/admin/shops/{with_quick['shop_id']}/sources",
        {
            "slug": "rd-index",
            "access": "wholesale",
            "decode": "private_api",
            "delivers_full": ["catalogue", "price", "availability"],
        },
    )
    rows = {
        c["source_id"]: c
        for c in client.get("/api/admin/scheduler", headers=auth(token)).json()["channels"]
    }
    assert rows[with_quick["id"]]["has_quick"] is True
    assert rows[without["id"]]["has_quick"] is False


# --- settling what a run brought ---


def test_a_finished_run_is_placed_without_anybody_calling_the_matcher(client, event_loop):
    """The pipeline stopped at "read": a listing waited, unplaced, until a person called the
    matcher. The scheduler settles a finished run now — the rebuild, the ladder, promotion."""
    from tests.test_matching import a_shop_we_can_build_from, offer_from

    token = admin_token(client)
    _, source, _, _ = a_shop_we_can_build_from(client, token)
    offer_id = offer_from(
        client,
        token,
        source["id"],
        {
            "name": "Apple iPhone 15 256 GB",
            "brand": "Apple",
            "model": "iPhone 15",
            "ean": "0194253000001",
        },
    )
    before = client.get(f"/api/admin/offers/{offer_id}/trace", headers=auth(token)).json()
    assert before["match"] is None

    event_loop.run_until_complete(scheduler().settle(run_id=0))

    after = client.get(f"/api/admin/offers/{offer_id}/trace", headers=auth(token)).json()
    assert after["match"] is not None, after["queue"]
    assert after["entry"]["model"] == "iPhone 15"


def test_settling_writes_what_it_placed_onto_the_run(client, event_loop):
    """So the run's own flow can show the last node filling in."""
    from tests.test_runs import channel, start

    token = admin_token(client)
    source = channel(client, token, cron_full=None, cron_quick=None)
    run = start(client, token, source["id"])

    event_loop.run_until_complete(scheduler().settle(run_id=run["id"]))

    progress = client.get(f"/api/admin/runs/{run['id']}", headers=auth(token)).json()["progress"]
    assert progress["phase"] == "settled"
    assert set(progress["settled"]) == {"renamed", "matched", "promoted", "matched_after"}


def test_a_settling_that_fails_says_so_on_the_run(client, event_loop, monkeypatch):
    """Otherwise the run reads "waiting to be placed" for ever."""
    from app.features.matching.service import MatchingService
    from tests.test_runs import channel, start

    async def broken(self, *, limit):
        raise RuntimeError("the matcher fell over")

    monkeypatch.setattr(MatchingService, "rebuild_named_from_a_stale_reading", broken)
    token = admin_token(client)
    source = channel(client, token, cron_full=None, cron_quick=None)
    run = start(client, token, source["id"])

    event_loop.run_until_complete(scheduler().settle(run_id=run["id"]))

    progress = client.get(f"/api/admin/runs/{run['id']}", headers=auth(token)).json()["progress"]
    assert progress["phase"] == "unsettled"
    assert "the matcher fell over" in progress["settle_error"]
