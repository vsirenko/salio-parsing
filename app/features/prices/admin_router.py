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
from app.features.prices.schemas import AvailabilityEventRead, PriceEventRead, PriceSeries
from app.schemas.common import ErrorResponse
from app.schemas.pagination import Page, Pagination

router = APIRouter(prefix="/price-history", tags=["admin: prices"])
availability_router = APIRouter(prefix="/availability-history", tags=["admin: prices"])

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
    items, total = await service.price_history(
        pagination,
        offer_id=offer_id,
        variant_id=variant_id,
        condition=condition,
        since=since,
        until=until,
    )
    return Page[PriceEventRead].of(items, total, pagination)


@router.get(
    "/series",
    response_model=PriceSeries,
    summary="A price chart's data for one entry or one family",
    responses={
        404: {"model": ErrorResponse, "description": "Variant or product not found"},
        422: {
            "model": ErrorResponse,
            "description": "Neither or both of variant_id and product_id",
        },
    },
)
async def series(
    service: PriceServiceDep,
    variant_id: Annotated[int | None, Query(description="One catalogue entry")] = None,
    product_id: Annotated[int | None, Query(description="A family: every entry in it")] = None,
    market_code: Annotated[str, Query(min_length=2, max_length=2)] = "LV",
    condition: Annotated[str, Query(description="new, refurbished or used")] = "new",
    days: Annotated[int, Query(ge=1, le=365, description="Up to and including today")] = 90,
    with_out_of_stock: Annotated[
        bool, Query(description="Count listings the shop says it has none of")
    ] = False,
) -> PriceSeries:
    """By day: the lowest, median and highest price across the listings on sale, and each
    shop's lowest as a line of its own. A listing's price is its last change before the day
    ended, and it counts only between its first and last sighting. The listings are the ones
    matched to the scope now, so correcting a match moves that listing's history too."""
    return await service.series(
        variant_id=variant_id,
        product_id=product_id,
        market_code=market_code,
        condition=condition,
        days=days,
        with_out_of_stock=with_out_of_stock,
    )


@availability_router.get(
    "", response_model=Page[AvailabilityEventRead], summary="Read the availability history"
)
async def availability_history(
    service: PriceServiceDep,
    pagination: CursorParams,
    offer_id: Annotated[int | None, Query(description="One listing")] = None,
    variant_id: Annotated[int | None, Query(description="Everything matched to a variant")] = None,
    condition: Annotated[str | None, Query(description="new, refurbished or used")] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> Page[AvailabilityEventRead]:
    """Its own series, not a column on the price.

    Availability arrives through channels that carry no price — a stock ping, a webhook, a
    faster poll of the same page — and recording one of those as a price event would mean
    repeating the last known price and calling it an observation. They also move at
    different rates: stock flips several times a day where a price changes in a week.
    """
    items, total = await service.availability_history(
        pagination,
        offer_id=offer_id,
        variant_id=variant_id,
        condition=condition,
        since=since,
        until=until,
    )
    return Page[AvailabilityEventRead].of(items, total, pagination)
