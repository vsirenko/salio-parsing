"""One execution of one channel: starting it, judging it, and deciding what is due.

The scheduler process is elsewhere. Everything it decides is here, as ordinary queries
over `runs` and `sources` — so what it would do can be asserted without starting it.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from croniter import CroniterBadCronError, croniter
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.models import (
    Category,
    Offer,
    RawOffer,
    Run,
    SchedulerHeartbeat,
    Shop,
    ShopMarket,
    Source,
)
from app.db.query import paginated
from app.features.runs.schemas import (
    ChannelSchedule,
    Check,
    Due,
    Job,
    Kind,
    RunProgress,
    RunRead,
    RunResult,
    SchedulerStatus,
    Status,
)
from app.schemas.pagination import Pagination

# A slot missed by more than this is let go rather than caught up. A crawl six hours late
# is answering a question nobody asked any more, and the next slot is along shortly.
CATCH_UP = timedelta(hours=6)


class RunService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- starting ---

    async def start(self, source_id: int, kind: Kind, *, queued: bool = False) -> RunRead:
        """A run of a channel: running, when the scheduler starts it and spawns its worker
        in the same breath, or queued, when a person asks and the scheduler's next tick
        gives it one."""
        source = await self._source(source_id)
        audit.set_target("source", source_id)
        if kind is Kind.QUICK and not source.delivers_quick:
            raise ValidationError(
                f"'{source.slug}' has no quick pass: it delivers nothing cheaply, so there"
                " is nothing to run.",
                code="no_quick_pass",
            )

        # Read off the row before the flush: a rollback expires the object, and reaching
        # for it while handling the failure sends it back to the database mid-rollback.
        slug = source.slug

        status = Status.QUEUED if queued else Status.RUNNING
        run = Run(source_id=source_id, kind=kind.value, status=status.value)
        self.session.add(run)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            # The partial unique index. Two schedulers, or one and an impatient human.
            await self.session.rollback()
            raise ConflictError(f"A {kind.value} run of '{slug}' is already going") from exc

        await self.session.refresh(run)
        audit.record_changes(started_run=run.id, kind=kind.value)
        return RunRead.model_validate(run)

    async def job(self, run_id: int) -> Job:
        """What a collector is being asked to do.

        The channel's declaration travels with the run rather than being passed on a
        command line, so a worker restarted by hand asks the same question and gets the
        same answer as one the scheduler spawned.
        """
        run = await self._run(run_id)
        source = await self._source(run.source_id)
        kind = Kind(run.kind)
        # Attached, not enabled. `is_enabled` says where a shop is *shown*, and collecting
        # before opening a market is the point of having the two apart — a storefront that
        # opens onto an empty catalogue opens onto nothing. Ingestion does not check the
        # flag either; this used to, so a shop attached and not yet shown collected 1394
        # products and then had nowhere to put them.
        markets = (
            await self.session.scalars(
                select(ShopMarket.market_code)
                .where(ShopMarket.shop_id == source.shop_id)
                .order_by(ShopMarket.market_code)
            )
        ).all()

        return Job(
            run_id=run.id,
            source_id=source.id,
            source_slug=source.slug,
            kind=kind,
            access=source.access,
            decode=source.decode,
            base_url=source.base_url,
            market_codes=list(markets),
            # Chosen here rather than by the worker: the pass and the facts it is expected
            # to bring back are one decision, and splitting it invites them to disagree.
            # A reparse re-reads full snapshots, so it is expected to bring back what a
            # full pass brings back.
            delivers=list(source.delivers_quick if kind is Kind.QUICK else source.delivers_full),
        )

    # --- finishing ---

    async def finish(self, run_id: int, result: RunResult) -> RunRead:
        run = await self._run(run_id)
        if run.finished_at is not None:
            raise ConflictError(f"Run {run_id} already finished as '{run.status}'")

        source = await self._source(run.source_id)
        audit.set_target("source", run.source_id)

        run.items_seen = result.items_seen
        run.items_ingested = result.items_ingested
        run.items_failed = result.items_failed
        run.coverage = dict(result.coverage)
        run.error = result.error
        run.finished_at = datetime.now(UTC)

        if result.error is not None:
            # The worker itself broke. Judging its numbers would be judging a crash.
            run.status = Status.FAILED.value
            run.contract = {"verdict": "not_evaluated", "checks": []}
        else:
            checks = await self._contract(source, run)
            passed = all(check.passed for check in checks)
            run.status = (Status.OK if passed else Status.REJECTED).value
            run.contract = {
                "verdict": "ok" if passed else "rejected",
                "checks": [check.model_dump(exclude_none=True) for check in checks],
            }

        await self.session.flush()
        await self.session.refresh(run)
        audit.record_changes(
            finished_run=run.id, status=run.status, verdict=run.contract.get("verdict")
        )
        return RunRead.model_validate(run)

    async def _contract(self, source: Source, run: Run) -> list[Check]:
        """What this channel's own numbers have to look like for its absences to be believed.

        Only facts the channel claims to deliver are asked about: checking price coverage
        on a pass that never carries a price would reject every run of it forever.
        """
        checks: list[Check] = []

        if source.min_items is not None:
            checks.append(
                Check(
                    name="min_items",
                    passed=run.items_seen >= source.min_items,
                    got=run.items_seen,
                    limit=source.min_items,
                )
            )

        # Compared within a kind: a reparse sees the snapshot store and a crawl sees the
        # shop, so holding one against the other would reject whichever ran second.
        baseline = await self._last_ok_items(source.id, run.kind, before=run.id)
        if baseline is None or baseline == 0:
            checks.append(
                Check(name="max_drop_pct", passed=True, note="no accepted run to compare against")
            )
        else:
            # Measured against the last run that ended `ok`, not the previous run of this
            # kind. Against the previous one, two broken crawls in a row pass the second:
            # it fell only a little, from an already-wrong number.
            dropped = max(0.0, (baseline - run.items_seen) / baseline * 100)
            checks.append(
                Check(
                    name="max_drop_pct",
                    passed=dropped <= source.max_drop_pct,
                    got=round(dropped, 2),
                    limit=float(source.max_drop_pct),
                )
            )

        delivers = source.delivers_quick if run.kind == Kind.QUICK.value else source.delivers_full
        if "price" in delivers:
            got = float(run.coverage.get("price", 0.0))
            checks.append(
                Check(
                    name="min_price_coverage",
                    passed=Decimal(str(got)) >= source.min_price_coverage,
                    got=got,
                    limit=float(source.min_price_coverage),
                )
            )

        return checks

    # --- what the scheduler decides ---

    async def sweep(self) -> int:
        """Close every live run as interrupted. Called once, at scheduler startup.

        Not a timeout: the scheduler is single by construction, so anything still running
        when it starts has no process behind it. The count is also an honest metric — it
        is how often we are being killed.
        """
        result = await self.session.execute(
            update(Run)
            # A queued run has no process behind it by design; it waits for this scheduler.
            .where(Run.finished_at.is_(None), Run.status == Status.RUNNING.value)
            .values(status=Status.INTERRUPTED.value, finished_at=datetime.now(UTC))
        )
        return result.rowcount or 0

    async def report_progress(self, run_id: int, progress: RunProgress) -> None:
        """What a running run has done so far, from its worker."""
        run = await self._run(run_id)
        if run.status != Status.RUNNING.value:
            raise ConflictError(f"Run {run_id} is {run.status}, not running")
        run.progress = {**(run.progress or {}), **progress.model_dump(exclude_none=True)}
        await self.session.flush()

    async def record_settled(self, run_id: int, settled: dict[str, int] | None) -> None:
        """What settling a finished run placed, from the scheduler; `None` as it begins."""
        run = await self.session.get(Run, run_id)
        if run is None:
            return
        if settled is None:
            run.progress = {**(run.progress or {}), "phase": "settling"}
        else:
            run.progress = {**(run.progress or {}), "phase": "settled", "settled": settled}
        await self.session.flush()

    async def queued(self) -> list[int]:
        """The runs asked for by hand, oldest first."""
        rows = await self.session.scalars(
            select(Run.id).where(Run.status == Status.QUEUED.value).order_by(Run.started_at, Run.id)
        )
        return list(rows.all())

    async def begin(self, run_id: int) -> bool:
        """Take a queued run: running from now. False if somebody took it first."""
        result = await self.session.execute(
            update(Run)
            .where(Run.id == run_id, Run.status == Status.QUEUED.value)
            .values(status=Status.RUNNING.value, started_at=datetime.now(UTC))
        )
        return bool(result.rowcount)

    async def due(self, *, now: datetime | None = None) -> list[Due]:
        """Which channels should be started right now.

        Reads the most recent slot at or before `now` rather than projecting forward from
        the last run: a channel that has never run, or that was off for a week, would
        otherwise have its next slot computed from a point so far back that it is always
        outside the catch-up window and never starts at all.
        """
        now = now or datetime.now(UTC)
        sources = (
            await self.session.scalars(select(Source).where(Source.is_enabled.is_(True)))
        ).all()
        last_started = await self._last_started()
        live = await self._live()

        due: list[Due] = []
        for source in sources:
            for kind, expression in (
                (Kind.FULL, source.cron_full),
                (Kind.QUICK, source.cron_quick),
            ):
                if not expression or (source.id, kind.value) in live:
                    continue
                try:
                    slot = croniter(expression, now).get_prev(datetime)
                except (CroniterBadCronError, ValueError):
                    # A malformed cron stops that channel, not the whole tick.
                    continue

                last = last_started.get((source.id, kind.value))
                if last is not None and last >= slot:
                    continue
                if now - slot > CATCH_UP:
                    continue
                due.append(Due(source_id=source.id, kind=kind, due_at=slot))

        return sorted(due, key=lambda item: (item.due_at, item.source_id))

    # --- the scheduler itself ---

    async def beat(self, *, started_at: datetime, pid: int, running: int, started: int) -> None:
        """The scheduler saying it is alive: one row, rewritten every tick."""
        now = datetime.now(UTC)
        row = await self.session.get(SchedulerHeartbeat, 1)
        if row is None:
            row = SchedulerHeartbeat(id=1, started_at=started_at, ticked_at=now, pid=pid)
            self.session.add(row)
        row.started_at, row.ticked_at, row.pid = started_at, now, pid
        row.running, row.started_last_tick = running, started
        await self.session.flush()

    async def heartbeat_is_fresh(self, *, now: datetime | None = None) -> bool:
        row = await self.session.get(SchedulerHeartbeat, 1)
        if row is None:
            return False
        now = now or datetime.now(UTC)
        return now - row.ticked_at <= timedelta(seconds=3 * settings.scheduler_tick_seconds)

    async def status(self, *, now: datetime | None = None) -> SchedulerStatus:
        """Alive or not, what is running, what is due, and every channel's next slot."""
        now = now or datetime.now(UTC)
        beat = await self.session.get(SchedulerHeartbeat, 1)
        live = (
            await self.session.scalars(
                select(Run).where(Run.finished_at.is_(None)).order_by(Run.started_at)
            )
        ).all()
        latest = (
            select(Run.id)
            .where(Run.source_id == Source.id)
            .order_by(Run.started_at.desc(), Run.id.desc())
            .limit(1)
            .correlate(Source)
            .scalar_subquery()
        )
        rows = (
            await self.session.execute(
                select(Source, Shop.name, Category.slug, latest)
                .join(Shop, Shop.id == Source.shop_id)
                .outerjoin(Category, Category.id == Source.category_id)
                .order_by(Shop.name, Source.slug)
            )
        ).all()
        last_ids = [run_id for *_, run_id in rows if run_id is not None]
        runs = {
            run.id: run
            for run in (await self.session.scalars(select(Run).where(Run.id.in_(last_ids)))).all()
        }
        channels = [
            ChannelSchedule(
                source_id=source.id,
                source=source.slug,
                shop=shop,
                category=category,
                is_enabled=source.is_enabled,
                has_quick=bool(source.delivers_quick),
                cron_full=source.cron_full,
                cron_quick=source.cron_quick,
                next_full_at=_next(source.cron_full, now) if source.is_enabled else None,
                next_quick_at=_next(source.cron_quick, now) if source.is_enabled else None,
                last_run=RunRead.model_validate(runs[run_id]) if run_id in runs else None,
            )
            for source, shop, category, run_id in rows
        ]
        return SchedulerStatus(
            alive=await self.heartbeat_is_fresh(now=now),
            started_at=beat.started_at if beat else None,
            ticked_at=beat.ticked_at if beat else None,
            pid=beat.pid if beat else None,
            tick_seconds=settings.scheduler_tick_seconds,
            progress={
                r.id: await self._seen_since(r.source_id, r.started_at)
                for r in live
                if r.status == Status.RUNNING.value
            },
            queued=[RunRead.model_validate(r) for r in live if r.status == Status.QUEUED.value],
            running=[RunRead.model_validate(r) for r in live if r.status == Status.RUNNING.value],
            due=await self.due(now=now),
            channels=channels,
        )

    async def _seen_since(self, source_id: int, since: datetime) -> int:
        """Listings of a channel observed since a moment, whatever their bytes were."""
        return (
            await self.session.scalar(
                select(func.count(func.distinct(Offer.id)))
                .join(RawOffer, RawOffer.offer_id == Offer.id)
                .where(RawOffer.source_id == source_id, Offer.last_seen_at >= since)
            )
        ) or 0

    async def _last_started(self) -> dict[tuple[int, str], datetime]:
        rows = await self.session.execute(
            select(Run.source_id, Run.kind, func.max(Run.started_at)).group_by(
                Run.source_id, Run.kind
            )
        )
        return {(source_id, kind): started for source_id, kind, started in rows.all()}

    async def _live(self) -> set[tuple[int, str]]:
        rows = await self.session.execute(
            select(Run.source_id, Run.kind).where(Run.finished_at.is_(None))
        )
        return {(source_id, kind) for source_id, kind in rows.all()}

    async def _last_ok_items(self, source_id: int, kind: str, *, before: int) -> int | None:
        return await self.session.scalar(
            select(Run.items_seen)
            .where(
                Run.source_id == source_id,
                Run.kind == kind,
                Run.status == Status.OK.value,
                Run.id != before,
            )
            .order_by(Run.started_at.desc(), Run.id.desc())
            .limit(1)
        )

    # --- reading it back ---

    async def runs(
        self,
        pagination: Pagination,
        *,
        source_id: int | None = None,
        status: Status | None = None,
    ) -> tuple[list[RunRead], int]:
        stmt = select(Run)
        if source_id is not None:
            stmt = stmt.where(Run.source_id == source_id)
        if status is not None:
            stmt = stmt.where(Run.status == status.value)
        rows, total = await paginated(
            self.session, stmt.order_by(Run.started_at.desc(), Run.id.desc()), pagination
        )
        return [RunRead.model_validate(row) for row in rows], total

    async def get(self, run_id: int) -> RunRead:
        return RunRead.model_validate(await self._run(run_id))

    async def _run(self, run_id: int) -> Run:
        run = await self.session.get(Run, run_id)
        if run is None:
            raise NotFoundError(f"Run {run_id} not found")
        return run

    async def _source(self, source_id: int) -> Source:
        source = await self.session.get(Source, source_id)
        if source is None:
            raise NotFoundError(f"Source {source_id} not found")
        return source


def _next(expression: str | None, now: datetime) -> datetime | None:
    """The next slot of a cron, or nothing for no schedule or one that does not parse."""
    if not expression:
        return None
    try:
        return croniter(expression, now).get_next(datetime)
    except (CroniterBadCronError, ValueError):
        return None
