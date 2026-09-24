"""The process that decides when a channel is collected.

    python -m app.features.runs.scheduler            run it
    python -m app.features.runs.scheduler --once     one tick and exit

Its own process rather than a thread inside the API: there it would be started once per
uvicorn worker and die with the one that happened to hold it. Here it is one process whose
uniqueness the database enforces, and whose crash takes nothing else with it.

What it decides is not here. `RunService.due` is an ordinary query and is tested through
`GET /api/admin/runs/due`; this file is only the clock, the lock and the subprocesses.
"""

import argparse
import asyncio
import logging
import os
import shlex
import signal
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import settings
from app.core.exceptions import AppError
from app.db.session import engine, session_factory
from app.features.judge.service import JudgeService
from app.features.matching.service import MatchingService
from app.features.runs.schemas import Kind, RunResult
from app.features.runs.service import RunService

log = logging.getLogger(__name__)

# Any constant would do; it only has to be the same in every process that competes for it.
LOCK_KEY = 0x5A11_0C0C


class Busy(Exception):
    """Another scheduler holds the lock. There is nothing to do but exit."""


class Worker:
    """One spawned run, and what the scheduler still owes it.

    The scheduler finishes a run its worker did not, because it is the only thing that
    knows the worker is gone. Left alone, a crashed worker would hold that channel's live
    slot until the next restart swept it.
    """

    def __init__(
        self,
        run_id: int,
        source_id: int,
        kind: Kind,
        process: asyncio.subprocess.Process,
    ) -> None:
        self.run_id = run_id
        self.source_id = source_id
        self.kind = kind
        self.process = process
        self.started = datetime.now(UTC)

    @property
    def overdue(self) -> bool:
        return datetime.now(UTC) - self.started > timedelta(minutes=settings.run_timeout_minutes)


# How much settling one finished run may do. Bounded, because settling holds the tick: a
# bound this size is every listing of the largest shop here, twice over.
SETTLE_LIMIT = 5000
SETTLE_ROUNDS = 5


class Scheduler:
    def __init__(self) -> None:
        self.workers: dict[int, Worker] = {}
        self.stopping = False
        self._lock: AsyncConnection | None = None
        self.started_at = datetime.now(UTC)

    # --- being the only one ---

    async def acquire(self) -> None:
        """Take the advisory lock, on a connection of its own.

        A pooled connection would be recycled and take the lock with it, which is the
        quiet version of running two schedulers.
        """
        connection = await engine.connect()
        held = await connection.scalar(text("select pg_try_advisory_lock(:key)"), {"key": LOCK_KEY})
        if not held:
            await connection.close()
            raise Busy("another scheduler holds the lock")
        self._lock = connection

    async def release(self) -> None:
        if self._lock is not None:
            await self._lock.close()
            self._lock = None

    # --- the loop ---

    async def run_forever(self, *, once: bool = False) -> None:
        await self.acquire()
        swept = await self._sweep()
        if swept:
            # Not an error to report and move past: it is the count of how often something
            # kills us, and the only place it is visible.
            log.warning("swept %d run(s) left behind by a previous scheduler", swept)

        try:
            while not self.stopping:
                await self.reap()
                started = await self.tick()
                await self.beat(started)
                if once:
                    return
                await asyncio.sleep(settings.scheduler_tick_seconds)
        finally:
            await self.shutdown()

    async def tick(self) -> int:
        """Start what was asked for by hand, then whatever is due, while there is room."""
        room = settings.scheduler_max_running - len(self.workers)
        if room <= 0:
            return 0

        started = 0
        async with session_factory() as session:
            asked = await RunService(session).queued()
        for run_id in asked[:room]:
            if await self._take(run_id):
                started += 1
        room -= started
        if room <= 0:
            return started

        async with session_factory() as session:
            due = await RunService(session).due()

        for item in due[:room]:
            if await self._spawn(item.source_id, item.kind):
                started += 1
        return started

    async def _take(self, run_id: int) -> bool:
        """A queued run: running from now, with a worker of its own."""
        async with session_factory() as session:
            service = RunService(session)
            if not await service.begin(run_id):
                return False
            run = await service.get(run_id)
            await session.commit()
        return await self._worker_for(run.id, run.source_id, Kind(run.kind))

    async def beat(self, started: int) -> None:
        """Say this scheduler is alive. A failure to say so is logged and never fatal: the
        heartbeat is for whoever watches, and a scheduler that stopped over it would be
        the outage it exists to reveal."""
        try:
            async with session_factory() as session:
                await RunService(session).beat(
                    started_at=self.started_at,
                    pid=os.getpid(),
                    running=len(self.workers),
                    started=started,
                )
                await session.commit()
        except Exception as error:  # noqa: BLE001 - see the docstring
            log.warning("could not record the heartbeat: %s", error)

    async def _spawn(self, source_id: int, kind: Kind) -> bool:
        async with session_factory() as session:
            service = RunService(session)
            try:
                run = await service.start(source_id, kind)
            except AppError as error:
                # Someone started it by hand between the query and here, or the channel
                # changed underneath. One channel's problem, not the tick's.
                log.info("not starting %s/%s: %s", source_id, kind.value, error)
                return False
            await session.commit()
        return await self._worker_for(run.id, source_id, kind)

    async def _worker_for(self, run_id: int, source_id: int, kind: Kind) -> bool:
        command = settings.worker_command.format(
            run_id=run_id, source_id=source_id, kind=kind.value
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *shlex.split(command),
                env={**os.environ, "RUN_ID": str(run_id)},
            )
        except OSError as error:
            await self._finish(run_id, f"could not spawn worker: {error}")
            return False

        self.workers[run_id] = Worker(run_id, source_id, kind, process)
        log.info("started run %d: %s", run_id, command)
        return True

    async def reap(self) -> None:
        """Collect finished workers, and kill the ones that stopped answering."""
        for worker in list(self.workers.values()):
            if worker.process.returncode is None:
                if worker.overdue:
                    log.warning("run %d passed its timeout, killing it", worker.run_id)
                    worker.process.kill()
                    await worker.process.wait()
                    del self.workers[worker.run_id]
                    await self._finish(
                        worker.run_id,
                        f"killed after {settings.run_timeout_minutes} minutes",
                    )
                continue

            del self.workers[worker.run_id]
            if worker.process.returncode != 0:
                await self._finish(worker.run_id, f"worker exited with {worker.process.returncode}")
            elif worker.kind in (Kind.FULL, Kind.REPARSE):
                await self.settle(worker.run_id)

    async def settle(self, run_id: int) -> None:
        """Place what a finished run collected, the way a person used to by hand.

        The rebuild first, so entries follow readings that moved; then the listings nobody
        has placed; then promotion of what can start an entry; then the ladder once more,
        for the listings that can now join what was just made. A failure here is logged and
        never stops the scheduler: the listings wait in the queue, which is where they were.
        """
        try:
            async with session_factory() as session:
                await RunService(session).record_settled(run_id, None)
                await session.commit()
                matching = MatchingService(session, judge=JudgeService(session))
                renamed = 0
                for _ in range(SETTLE_ROUNDS):
                    report = await matching.rebuild_named_from_a_stale_reading(limit=SETTLE_LIMIT)
                    renamed += report.renamed + report.merged
                    if not report.found:
                        break
                first = await matching.run(limit=SETTLE_LIMIT)
                promoted = await matching.promote_queue(limit=SETTLE_LIMIT)
                again = await matching.run(limit=SETTLE_LIMIT)
                await RunService(session).record_settled(
                    run_id,
                    {
                        "renamed": renamed,
                        "matched": first.matched,
                        "promoted": promoted.promoted,
                        "matched_after": again.matched,
                    },
                )
                await session.commit()
            log.info(
                "run %d settled: %d renamed, %d matched, %d promoted, %d matched after",
                run_id,
                renamed,
                first.matched,
                promoted.promoted,
                again.matched,
            )
        except Exception as error:  # noqa: BLE001 - see the docstring
            log.warning("run %d could not be settled: %s", run_id, error)

    async def _finish(self, run_id: int, error: str) -> None:
        """Close a run its worker never closed.

        A worker that reported for itself is left alone: this only fires when the process
        is gone and the row is still open, which the conflict check confirms.
        """
        async with session_factory() as session:
            service = RunService(session)
            try:
                await service.finish(run_id, RunResult(items_seen=0, items_ingested=0, error=error))
            except AppError:
                return  # it finished on its own; its own numbers are the better ones
            await session.commit()

    async def _sweep(self) -> int:
        async with session_factory() as session:
            swept = await RunService(session).sweep()
            await session.commit()
            return swept

    # --- stopping ---

    def stop(self) -> None:
        self.stopping = True

    async def shutdown(self) -> None:
        """Wait for what is running rather than orphaning it.

        A killed worker leaves an open row that only the next startup would sweep, so the
        channel would be unavailable until then.
        """
        for worker in list(self.workers.values()):
            try:
                await asyncio.wait_for(worker.process.wait(), timeout=30)
            except TimeoutError:
                worker.process.kill()
                await worker.process.wait()
                self.workers.pop(worker.run_id, None)
                await self._finish(worker.run_id, "scheduler stopped")

        # Reaped rather than closed wholesale: a worker that exited on its own has either
        # already recorded its own verdict or left an exit code worth keeping, and
        # "scheduler stopped" on top of either would be the scheduler taking the blame for
        # something it did not do.
        await self.reap()
        await self.release()


async def healthy() -> int:
    """0 when the heartbeat is fresher than three ticks, 1 otherwise."""
    async with session_factory() as session:
        return 0 if await RunService(session).heartbeat_is_fresh() else 1


async def main(*, once: bool = False) -> int:
    scheduler = Scheduler()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, scheduler.stop)

    try:
        await scheduler.run_forever(once=once)
    except Busy:
        log.error("another scheduler is already running")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    from app.core.logging import configure_logging

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="one tick and exit")
    parser.add_argument(
        "--healthy",
        action="store_true",
        help="exit 0 if the running scheduler ticked recently, 1 if not — the container check",
    )
    arguments = parser.parse_args()

    configure_logging()
    if arguments.healthy:
        raise SystemExit(asyncio.run(healthy()))
    raise SystemExit(asyncio.run(main(once=arguments.once)))
