"""Query helpers shared by the services."""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Select, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Offer, RawOffer, Run
from app.schemas.pagination import Pagination


async def paginated[T](
    session: AsyncSession, stmt: Select[tuple[T]], pagination: Pagination
) -> tuple[Sequence[T], int]:
    """Run a statement twice: once counted, once windowed.

    The count runs over the same filters, so `total` always matches what the caller
    asked for. Ordering belongs to the caller — it differs per entity.
    """
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = await session.scalars(stmt.limit(pagination.limit).offset(pagination.offset))
    return rows.all(), total or 0


def ordered[T](
    stmt: Select[T],
    pagination: Pagination,
    columns: Mapping[str, Any],
    tiebreak: Any,
) -> Select[T]:
    """Order by the keys the caller asked for, then by `tiebreak`, always.

    `columns` maps each sort key the endpoint allows to the expression it sorts by. Nulls go
    last whichever way a key runs: a family with no price is not the cheapest one. The
    tie-breaker is what keeps offset pages stable — ten rows with one title would otherwise
    come back in any order, and page two would repeat some of page one.
    """
    order = []
    for key, descending in pagination.sort:
        column = columns[key]
        order.append(column.desc().nulls_last() if descending else column.asc().nulls_last())
    return stmt.order_by(*order, tiebreak)


async def paginated_rows(
    session: AsyncSession, stmt: Select[Any], pagination: Pagination
) -> tuple[Sequence[Any], int]:
    """`paginated`, for a statement that selects several columns: the rows, not scalars.

    Counted on the filters alone, not on everything selected: a row built of correlated
    counts would otherwise compute them for every row in the table just to be counted, which
    made a page of families 0.57 s where the page itself costs a few milliseconds.
    """
    counted = stmt.with_only_columns(func.count(), maintain_column_froms=True).order_by(None)
    total = await session.scalar(counted)
    rows = await session.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    return rows.all(), total or 0


def offer_is_listed() -> Any:
    """Whether a listing is on sale now: seen by its channel's newest full pass that ended ok.

    The rule the pipeline counts by. A card the shop took down keeps its history and stops
    counting — its last price is not a price anybody can pay — and a channel that has never
    finished a full pass has not said anything is gone, so its listings stand.
    """
    # Said the other way round, which the planner can follow down two indexes: no full pass
    # of the listing's channel ended ok after it began without having seen the listing. As a
    # comparison with the newest pass's start it was a scan of every observation per page.
    return ~exists(
        select(RawOffer.id)
        .join(
            Run,
            (Run.source_id == RawOffer.source_id)
            & (Run.kind == "full")
            & (Run.status == "ok")
            & (Run.started_at > Offer.last_seen_at),
        )
        .where(RawOffer.offer_id == Offer.id)
    )
