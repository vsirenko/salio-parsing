"""Counting what reached each step of the pipeline, per channel and in total.

Read-only, and only over tables other features own: every model lives in
`app/db/models.py`, so this reads `runs`, `raw_offers`, `normalized_offers`, `offer_matches`,
`match_queue` and the catalogue directly and imports none of their code.
"""

from collections import Counter

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.features.pipeline.schemas import Edge, Pipeline, SourceFlow, Stage

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
select s.id, s.slug, sh.name as shop, c.slug as category, s.category_id,
       (s.cron_full is not null or s.cron_quick is not null) as scheduled,
       (select ru.status from runs ru where ru.source_id = s.id and ru.kind = 'full'
        order by ru.started_at desc, ru.id desc limit 1) as last_status,
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


def _flow(channel) -> SourceFlow:
    return SourceFlow(
        source_id=channel["id"],
        source=channel["slug"],
        shop=channel["shop"],
        category=channel["category"],
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
