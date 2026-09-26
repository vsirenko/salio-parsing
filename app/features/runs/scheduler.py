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
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import settings
from app.core.exceptions import AppError
from app.db.models import RereadRequest
from app.db.session import engine, session_factory
from app.features.judge.service import JudgeService
from app.features.matching.service import MatchingService
from app.features.offers.service import OfferService
from app.features.pipeline.service import PipelineService
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
        # The day the pipeline was last kept, so a tick asks the database once a day.
        self._kept_day: date | None = None

    # --- being the only one ---

    async def acquire(self) -> None:
        """Take the advisory lock, on a connection held for as long as the lock is.

        The connection comes from the pool, and a session-level advisory lock outlives a
        connection being handed back to it: closing is not releasing. So `release` unlocks
        first. Until 24.09.2026 it only closed, and the lock went back into the pool with the
        connection — invisible while the process exited after, and the tests' pool found it.
        """
        connection = await engine.connect()
        held = await connection.scalar(text("select pg_try_advisory_lock(:key)"), {"key": LOCK_KEY})
        if not held:
            await connection.close()
            raise Busy("another scheduler holds the lock")
        self._lock = connection

    async def release(self) -> None:
        if self._lock is not None:
            try:
                await self._lock.scalar(text("select pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
            finally:
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
                await self.reread()
                await self.beat(started)
                await self.keep_the_day()
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

    async def keep_the_day(self) -> None:
        """The pipeline's numbers for today, once: everything else it shows is counted as it
        is now, so a day not kept is a day nobody can look back at. Logged, never fatal."""
        today = datetime.now(UTC).date()
        if self._kept_day == today:
            return
        try:
            async with session_factory() as session:
                written = await PipelineService(session).take_snapshot(today)
                await session.commit()
            self._kept_day = today
            if written:
                log.info("kept the pipeline for %s: %d scope(s)", today, written)
        except Exception as error:  # noqa: BLE001 - see the docstring
            log.warning("could not keep the pipeline for %s: %s", today, error)

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
        """Collect finished workers, and kill the ones that stopped answering — or whose
        run a person cancelled, which closed the row under a process still working."""
        alive = [
            worker.run_id for worker in self.workers.values() if worker.process.returncode is None
        ]
        if alive:
            async with session_factory() as session:
                cancelled = await RunService(session).cancelled_among(alive)
            for run_id in cancelled:
                worker = self.workers.pop(run_id)
                log.info("run %d was cancelled, killing its worker", run_id)
                worker.process.kill()
                await worker.process.wait()
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
            elif worker.kind is Kind.REPARSE and await self._more_reparses_waiting():
                # Settling walks the whole queue, a minute or more, and the loop does nothing
                # else meanwhile: a reparse of twenty channels settled twenty times took an
                # hour on 25.09.2026 for runs of two seconds each. The last one settles for
                # all of them.
                async with session_factory() as session:
                    await RunService(session).record_settle_deferred(worker.run_id)
                    await session.commit()
            elif worker.kind in (Kind.FULL, Kind.REPARSE):
                await self.settle(worker.run_id)

    async def reread(self) -> None:
        """A batch of the oldest re-read a registry change asked for, once changes are quiet.

        A batch per tick, so collection is not held up behind a maker with three thousand
        listings; the request keeps where it got to. When the last batch is read the
        catalogue is settled the way a person did it by hand on 26.09.2026 — rebuild until
        nothing moves, split what holds two values of an axis, rebuild once more. A change
        arriving meanwhile starts the request over (`BrandService._ask_for_reread`), and a
        request is only finished if no change came while it was being settled. Logged,
        never fatal: a request that fails is closed with its error, not retried forever.
        """
        now = datetime.now(UTC)
        quiet = now - timedelta(seconds=settings.reread_quiet_seconds)
        request_id: int | None = None
        try:
            async with session_factory() as session:
                request = await session.scalar(
                    select(RereadRequest)
                    .where(RereadRequest.finished_at.is_(None), RereadRequest.requested_at <= quiet)
                    .order_by(RereadRequest.requested_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                if request is None:
                    return
                request_id, asked = request.id, request.requested_at
                request.started_at = request.started_at or now
                read, after = await OfferService(session).reread_brand(
                    request.brand_id,
                    request.category_id,
                    limit=settings.reread_batch,
                    after_id=request.after_offer_id,
                )
                request.read += read
                if after is not None:
                    request.after_offer_id = after
                    await session.commit()
                    return
                await session.commit()

                report = await self._settle_after_reread(session)
                request = await session.get(
                    RereadRequest, request_id, with_for_update=True, populate_existing=True
                )
                if request.requested_at != asked:
                    # Changed while it was being settled: read it again, with the words now.
                    await session.commit()
                    return
                request.report = report
                request.finished_at = datetime.now(UTC)
                await session.commit()
            log.info("re-read request %d finished: %s", request_id, report)
        except Exception as error:  # noqa: BLE001 - see the docstring
            log.warning("re-read request %s could not be finished: %s", request_id, error)
            if request_id is None:
                return
            try:
                async with session_factory() as session:
                    failed = await session.get(RereadRequest, request_id)
                    if failed is not None and failed.finished_at is None:
                        failed.error = str(error)[:500]
                        failed.finished_at = datetime.now(UTC)
                        await session.commit()
            except Exception:  # noqa: BLE001
                log.exception("and its failure could not be recorded")

    async def _settle_after_reread(self, session) -> dict[str, int]:
        matching = MatchingService(session, judge=JudgeService(session))
        report = {"renamed": 0, "merged": 0, "realigned": 0, "split": 0, "moved": 0}
        for _ in range(SETTLE_ROUNDS):
            rebuilt = await matching.rebuild_named_from_a_stale_reading(limit=SETTLE_LIMIT)
            await session.commit()
            report["renamed"] += rebuilt.renamed
            report["merged"] += rebuilt.merged
            report["realigned"] += rebuilt.realigned
            if not (rebuilt.found or rebuilt.realigned or rebuilt.merged or rebuilt.rebranded):
                break
        split = await matching.split_by_axis(limit=SETTLE_LIMIT)
        await session.commit()
        report["split"], report["moved"] = split.split, split.moved
        if split.split:
            rebuilt = await matching.rebuild_named_from_a_stale_reading(limit=SETTLE_LIMIT)
            await session.commit()
            report["renamed"] += rebuilt.renamed
            report["merged"] += rebuilt.merged
            report["realigned"] += rebuilt.realigned
        return report

    async def _more_reparses_waiting(self) -> bool:
        async with session_factory() as session:
            return await RunService(session).reparses_waiting()

    async def settle(self, run_id: int) -> None:
        """Place what a finished run collected, the way a person used to by hand.

        The rebuild first, so entries follow readings that moved; then the listings nobody
        has placed; then promotion of what can start an entry; then the ladder once more,
        for the listings that can now join what was just made. A failure here is logged and
        never stops the scheduler: the listings wait in the queue, which is where they were.
        """
        try:
            async with session_factory() as session:
                runs = RunService(session)
                await runs.record_settled(run_id, None)
                await session.commit()
                families_before = await runs.families_of(run_id)
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
                families_after = await runs.families_of(run_id)
                if families_after > families_before:
                    # A pass over readings already placed should fold families, not make
                    # them: more after a reparse is a rule or a registry change that split
                    # what was one, and it shows here rather than as a slow drift.
                    log.warning(
                        "run %d: its category went from %d families to %d",
                        run_id,
                        families_before,
                        families_after,
                    )
                await runs.record_settled(
                    run_id,
                    {
                        "renamed": renamed,
                        "matched": first.matched,
                        "promoted": promoted.promoted,
                        "matched_after": again.matched,
                        "families_before": families_before,
                        "families_after": families_after,
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
            try:
                async with session_factory() as session:
                    await RunService(session).record_unsettled(
                        run_id, f"{type(error).__name__}: {error}"
                    )
                    await session.commit()
            except Exception as again:  # noqa: BLE001 - the log line above already says it
                log.warning("run %d: could not record that: %s", run_id, again)

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
