"""Price history behind the admin panel: /api/admin/price-history

Read-only. Rows are written by ingestion and nothing edits or deletes one — a price that
was charged was charged, and the moment a history can be edited it stops being evidence of
anything.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import PriceServiceDep
from app.api.pagination import cursor_pagination_params
from app.features.prices.schemas import PriceEventRead
from app.schemas.pagination import Page, Pagination

router = APIRouter(prefix="/price-history", tags=["admin: prices"])

CursorParams = Annotated[Pagination, Depends(cursor_pagination_params())]


@router.get("", response_model=Page[PriceEventRead], summary="Read the price history")
async def history(
    service: PriceServiceDep,
    pagination: CursorParams,
    offer_id: Annotated[int | None, Query(description="One listing")] = None,
    variant_id: Annotated[int | None, Query(description="Everything matched to a variant")] = None,
    condition: Annotated[str | None, Query(description="new, refurbished or used")] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> Page[PriceEventRead]:
    """Newest first, by cursor — an append-only feed read by offset repeats rows as new
    ones arrive.

    A row says what a *listing* cost, not what a product cost. Filtering by `variant_id`
    uses the hint carried alongside, which is rewritten when a match changes; the row itself
    never moves, because what it records stayed true.
    """
    items, total = await service.history(
        pagination,
        offer_id=offer_id,
        variant_id=variant_id,
        condition=condition,
        since=since,
        until=until,
    )
    return Page[PriceEventRead].of(items, total, pagination)
