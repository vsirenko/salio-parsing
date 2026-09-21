"""Query helpers shared by the services."""

from collections.abc import Sequence

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
