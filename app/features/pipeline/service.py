"""Counting what reached each step of the pipeline, per channel and in total.

Read-only, and only over tables other features own: every model lives in
`app/db/models.py`, so this reads `runs`, `raw_offers`, `normalized_offers`, `offer_matches`,
`match_queue` and the catalogue directly and imports none of their code.
"""

from collections import Counter
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models import PipelineSnapshot
from app.features.pipeline.schemas import (
    Edge,
    Pipeline,
    PipelineDay,
    RunFlow,
    SourceFlow,
    Stage,
)

# One row per listing: its channel, whether the shop still lists it, its newest reading
# from a pass that carried the catalogue — the rule the matcher reads by — and where it
# stands. "Still listed" is seen by the channel's newest full pass that ended ok; a card the
# shop took down, or one a channel's filter now leaves out, keeps its history and stops
# counting.
LISTINGS = """
with latest as (
    select distinct on (r.offer_id) r.offer_id, r.source_id, r.id as raw_id
    from raw_offers r
    left join runs ru on ru.id = r.run_id
    where ru.kind is null or ru.kind <> 'quick'
    order by r.offer_id, r.fetched_at desc, r.id desc
),
reading as (
    select distinct on (n.raw_offer_id) n.raw_offer_id, n.model, n.gtin, n.identity
    from normalized_offers n
    order by n.raw_offer_id, n.id desc
),
required as (
    select ca.category_id, array_agg(a.key) as axes
    from category_attributes ca join attributes a on a.id = ca.attribute_id
    where ca.identity_bearing
    group by ca.category_id
),
last_ok as (
    select source_id, max(started_at) as started
    from runs where kind = 'full' and status = 'ok'
    group by source_id
)
select l.source_id,
       coalesce(o.last_seen_at >= lo.started, true) as listed,
       rd.raw_offer_id is not null as read,
       coalesce(rd.model, '') <> '' as with_model,
       rd.gtin is not null as with_gtin,
       coalesce(rd.identity ?& req.axes, false) as all_axes,
       -- Which of the required axes the reading lacks, each by name: one count of "not
       -- every axis" does not say whether it is the colour or the capacity that is missing.
       array(
           select axis from unnest(req.axes) as axis
           where rd.raw_offer_id is not null and not (rd.identity ? axis)
       ) as missing_axes,
       m.method,
       q.reason
from latest l
join offers o on o.id = l.offer_id
join sources s on s.id = l.source_id
left join reading rd on rd.raw_offer_id = l.raw_id
left join required req on req.category_id = s.category_id
left join last_ok lo on lo.source_id = l.source_id
left join offer_matches m on m.offer_id = l.offer_id and m.superseded_at is null
left join match_queue q on q.offer_id = l.offer_id
"""

CHANNELS = """
select s.id, s.slug, sh.id as shop_id, sh.name as shop, c.slug as category,
       c.name as category_name, s.category_id,
       (s.cron_full is not null or s.cron_quick is not null) as scheduled,
       (select ru.status from runs ru where ru.source_id = s.id and ru.kind = 'full'
        order by ru.started_at desc, ru.id desc limit 1) as last_status,
       (select ru.id from runs ru where ru.source_id = s.id and ru.kind = 'full'
        order by ru.started_at desc, ru.id desc limit 1) as last_run_id,
       (select ru.items_seen from runs ru where ru.source_id = s.id and ru.kind = 'full'
        order by ru.started_at desc, ru.id desc limit 1) as last_seen
from sources s
join shops sh on sh.id = s.shop_id
left join categories c on c.id = s.category_id
"""

CATALOGUE = """
select count(distinct v.id) as variants, count(distinct v.product_id) as products
from variants v
join products p on p.id = v.product_id and p.is_visible
where (cast(:category_id as integer) is null or v.category_id = :category_id)
  and (cast(:source_id as integer) is null or exists (
      select 1 from offer_matches m
      join raw_offers r on r.offer_id = m.offer_id
      where m.variant_id = v.id and m.superseded_at is null and r.source_id = :source_id))
"""

RUN = """
select ru.id, ru.kind, ru.status, ru.started_at, ru.finished_at, ru.error, ru.progress,
       ru.items_seen, ru.items_ingested, ru.items_failed,
       s.id as source_id, s.slug as source, sh.name as shop, c.slug as category
from runs ru
join sources s on s.id = ru.source_id
join shops sh on sh.id = s.shop_id
left join categories c on c.id = s.category_id
where ru.id = :run_id
"""

# The listings a run saw: the channel's stored readings whose bytes it delivered, changed or
# not — an unchanged page bumps `last_seen_at` and nothing else — while the run was open.
# A quick pass inside that window would count too; one channel runs one pass at a time.
RUN_LISTINGS = """
with seen as (
    select distinct on (r.offer_id) r.offer_id, r.id as raw_id, r.run_id
    from raw_offers r
    where r.source_id = :source_id
      and r.last_seen_at >= :started
      and r.last_seen_at <= coalesce(cast(:finished as timestamptz), now())
    order by r.offer_id, r.last_seen_at desc, r.id desc
),
reading as (
    select distinct on (n.raw_offer_id) n.raw_offer_id, n.model, n.gtin, n.identity
    from normalized_offers n
    where n.raw_offer_id in (select raw_id from seen)
    order by n.raw_offer_id, n.id desc
),
required as (
    select ca.category_id, array_agg(a.key) as axes
    from category_attributes ca join attributes a on a.id = ca.attribute_id
    where ca.identity_bearing
    group by ca.category_id
)
select o.first_seen_at >= :started as new_listing,
       se.run_id = :run_id as changed,
       rd.raw_offer_id is not null as read,
       coalesce(rd.model, '') <> '' as with_model,
       rd.gtin is not null as with_gtin,
       coalesce(rd.identity ?& req.axes, false) as all_axes,
       m.method,
       m.decided_at >= :started as placed_now,
       v.created_at >= :started as new_entry,
       m.variant_id,
       q.reason
from seen se
join offers o on o.id = se.offer_id
join sources s on s.id = :source_id
left join reading rd on rd.raw_offer_id = se.raw_id
left join required req on req.category_id = s.category_id
left join offer_matches m on m.offer_id = se.offer_id and m.superseded_at is null
left join variants v on v.id = m.variant_id
left join match_queue q on q.offer_id = se.offer_id
"""


class PipelineService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def summary(self, *, category: str | None = None, source: str | None = None) -> Pipeline:
        channels = (await self.session.execute(text(CHANNELS))).mappings().all()
        if category is not None and not any(c["category"] == category for c in channels):
            raise NotFoundError(f"No channel collects category {category!r}")
        if source is not None and not any(c["slug"] == source for c in channels):
            raise NotFoundError(f"Source {source!r} not found")
        chosen = [
            c
            for c in channels
            if (category is None or c["category"] == category)
            and (source is None or c["slug"] == source)
        ]
        ids = {c["id"] for c in chosen}

        rows = [
            row
            for row in (await self.session.execute(text(LISTINGS))).mappings().all()
            if row["source_id"] in ids
        ]
        flows = {c["id"]: _flow(c) for c in chosen}
        methods: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        missing: Counter[str] = Counter()
        delisted = 0
        for row in rows:
            flow = flows[row["source_id"]]
            if not row["listed"]:
                flow.delisted += 1
                delisted += 1
                continue
            flow.listed += 1
            flow.read += row["read"]
            flow.with_model += row["with_model"]
            flow.with_gtin += row["with_gtin"]
            flow.all_axes += row["all_axes"]
            for axis in row["missing_axes"] or []:
                flow.missing_axes[axis] = flow.missing_axes.get(axis, 0) + 1
                missing[axis] += 1
            if row["method"]:
                flow.placed += 1
                methods[row["method"]] += 1
            elif row["reason"]:
                flow.queued += 1
                reasons[row["reason"]] += 1

        category_id = chosen[0]["category_id"] if category is not None and chosen else None
        catalogue = (
            (
                await self.session.execute(
                    text(CATALOGUE),
                    {
                        "category_id": category_id,
                        "source_id": chosen[0]["id"] if source is not None and chosen else None,
                    },
                )
            )
            .mappings()
            .one()
        )

        def total(key: str) -> int:
            return sum(getattr(flow, key) for flow in flows.values())

        listed, read, placed, queued = (
            total("listed"),
            total("read"),
            total("placed"),
            total("queued"),
        )
        runs = Counter(c["last_status"] or "never" for c in chosen)
        stages = [
            Stage(
                key="channels",
                label="Channels",
                count=len(chosen),
                parts={"scheduled": sum(c["scheduled"] for c in chosen), **runs},
            ),
            Stage(
                key="collected",
                label="Collected by the last full pass",
                count=total("collected"),
                parts={},
            ),
            Stage(key="listed", label="Listed now", count=listed, parts={"delisted": delisted}),
            Stage(
                key="read",
                label="Read",
                count=read,
                parts={
                    "with_model": total("with_model"),
                    "with_gtin": total("with_gtin"),
                    "all_axes": total("all_axes"),
                },
                missing_axes=dict(missing.most_common()),
            ),
            Stage(key="placed", label="Placed", count=placed, parts=dict(methods.most_common())),
            Stage(key="queued", label="Queued", count=queued, parts=dict(reasons.most_common())),
            Stage(
                key="catalogue",
                label="Catalogue",
                count=catalogue["variants"],
                parts={"families": catalogue["products"]},
            ),
        ]
        edges = [
            Edge(source="channels", target="collected", count=total("collected")),
            Edge(source="collected", target="listed", count=listed),
            Edge(source="listed", target="read", count=read),
            Edge(source="read", target="placed", count=placed),
            Edge(source="read", target="queued", count=queued),
            Edge(source="placed", target="catalogue", count=catalogue["variants"]),
        ]
        return Pipeline(
            category=category,
            source=source,
            stages=stages,
            edges=edges,
            sources=sorted(flows.values(), key=lambda f: (f.shop, f.source)),
        )

    async def take_snapshot(self, day: date) -> int:
        """Keep today's numbers for everything and for each category, once. Returns how many
        scopes were written; nothing if the day is already kept."""
        kept = await self.session.scalar(
            select(func.count())
            .select_from(PipelineSnapshot)
            .where(PipelineSnapshot.day == day, PipelineSnapshot.scope == "all")
        )
        if kept:
            return 0
        channels = (await self.session.execute(text(CHANNELS))).mappings().all()
        scopes = [None, *sorted({c["category"] for c in channels if c["category"]})]
        for scope in scopes:
            flow = await self.summary(category=scope)
            self.session.add(PipelineSnapshot(day=day, scope=scope or "all", counts=_counts(flow)))
        await self.session.flush()
        return len(scopes)

    async def history(self, *, days: int, scope: str = "all") -> list[PipelineDay]:
        since = datetime.now(UTC).date() - timedelta(days=days - 1)
        rows = await self.session.scalars(
            select(PipelineSnapshot)
            .where(PipelineSnapshot.scope == scope, PipelineSnapshot.day >= since)
            .order_by(PipelineSnapshot.day)
        )
        return [PipelineDay(day=row.day, scope=row.scope, **row.counts) for row in rows]

    async def run(self, run_id: int) -> RunFlow:
        """One run's own pass, from the worker's counts to what settling it placed."""
        run = (await self.session.execute(text(RUN), {"run_id": run_id})).mappings().first()
        if run is None:
            raise NotFoundError(f"Run {run_id} not found")
        rows = (
            (
                await self.session.execute(
                    text(RUN_LISTINGS),
                    {
                        "run_id": run_id,
                        "source_id": run["source_id"],
                        "started": run["started_at"],
                        "finished": run["finished_at"],
                    },
                )
            )
            .mappings()
            .all()
        )
        progress = run["progress"] or {}
        methods: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        counts: Counter[str] = Counter()
        entries: set[int] = set()
        for row in rows:
            counts["seen"] += 1
            for key in ("new_listing", "changed", "read", "with_model", "with_gtin", "all_axes"):
                counts[key] += bool(row[key])
            if row["method"]:
                counts["placed"] += 1
                counts["placed_now"] += bool(row["placed_now"])
                methods[row["method"]] += 1
                if row["new_entry"]:
                    entries.add(row["variant_id"])
            elif row["reason"]:
                counts["queued"] += 1
                reasons[row["reason"]] += 1

        finished = run["status"] not in ("queued", "running")
        # While the worker runs its own report is the only word on how far it got; once it
        # has finished, the run's row carries the final count.
        discovered = run["items_seen"] if finished else progress.get("discovered")
        fetched = run["items_seen"] - run["items_failed"] if finished else progress.get("read", 0)
        failed = run["items_failed"] if finished else progress.get("failed", 0)
        handed = run["items_ingested"] if finished else progress.get("handed_over", 0)
        phase = progress.get("phase") or run["status"]
        if finished and phase == "reading":
            phase = run["status"]
        # Only a full pass or a reparse is settled; a quick one carries prices and nothing to
        # place, so once it has ended ok it is done. Run 316 waited for a settling that was
        # never coming, and its canvas kept moving.
        if phase == "ok" and run["kind"] == "quick":
            phase = "done"

        stages = [
            Stage(key="queued", label="Asked for", count=1, parts={}),
            Stage(key="discovered", label="Found on the shop", count=discovered or 0, parts={}),
            Stage(
                key="fetched", label="Read by the worker", count=fetched, parts={"failed": failed}
            ),
            Stage(key="handed_over", label="Handed over", count=handed, parts={}),
            Stage(
                key="read",
                label="Read by us",
                count=counts["read"],
                parts={
                    "new_listings": counts["new_listing"],
                    "changed": counts["changed"],
                    "with_model": counts["with_model"],
                    "with_gtin": counts["with_gtin"],
                    "all_axes": counts["all_axes"],
                },
            ),
            Stage(
                key="placed",
                label="Placed",
                count=counts["placed"],
                parts={"by_this_run": counts["placed_now"], **dict(methods.most_common())},
            ),
            Stage(
                key="waiting",
                label="Queued for review",
                count=counts["queued"],
                parts=dict(reasons.most_common()),
            ),
            Stage(
                key="new_entries",
                label="New catalogue entries",
                count=len(entries),
                parts=progress.get("settled") or {},
            ),
        ]
        edges = [
            Edge(source="queued", target="discovered", count=discovered or 0),
            Edge(source="discovered", target="fetched", count=fetched),
            Edge(source="fetched", target="handed_over", count=handed),
            Edge(source="handed_over", target="read", count=counts["read"]),
            Edge(source="read", target="placed", count=counts["placed"]),
            Edge(source="read", target="waiting", count=counts["queued"]),
            Edge(source="placed", target="new_entries", count=len(entries)),
        ]
        return RunFlow(
            run_id=run["id"],
            source=run["source"],
            shop=run["shop"],
            category=run["category"],
            kind=run["kind"],
            status=run["status"],
            started_at=run["started_at"],
            finished_at=run["finished_at"],
            error=run["error"],
            phase=phase,
            progress=progress,
            stages=stages,
            edges=edges,
        )


def _flow(channel) -> SourceFlow:
    return SourceFlow(
        source_id=channel["id"],
        source=channel["slug"],
        shop_id=channel["shop_id"],
        shop=channel["shop"],
        category=channel["category"],
        category_id=channel["category_id"],
        category_slug=channel["category"],
        category_name=channel["category_name"],
        last_run_id=channel["last_run_id"],
        scheduled=channel["scheduled"],
        last_run_status=channel["last_status"],
        collected=channel["last_seen"] or 0,
        listed=0,
        delisted=0,
        read=0,
        with_model=0,
        with_gtin=0,
        all_axes=0,
        placed=0,
        queued=0,
    )


def _counts(flow: Pipeline) -> dict:
    stages = {stage.key: stage for stage in flow.stages}
    read, placed, queued = stages["read"], stages["placed"], stages["queued"]
    return {
        "collected": stages["collected"].count,
        "listed": stages["listed"].count,
        "delisted": stages["listed"].parts.get("delisted", 0),
        "read": read.count,
        "with_model": read.parts.get("with_model", 0),
        "with_gtin": read.parts.get("with_gtin", 0),
        "all_axes": read.parts.get("all_axes", 0),
        "missing_axes": read.missing_axes,
        "placed": placed.count,
        "placed_by_method": placed.parts,
        "queued": queued.count,
        "queued_by_reason": queued.parts,
        "variants": stages["catalogue"].count,
        "families": stages["catalogue"].parts.get("families", 0),
    }
