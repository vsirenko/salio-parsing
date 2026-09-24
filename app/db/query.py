"""Query helpers shared by the services."""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    """`paginated`, for a statement that selects several columns: the rows, not scalars."""
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = await session.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    return rows.all(), total or 0
