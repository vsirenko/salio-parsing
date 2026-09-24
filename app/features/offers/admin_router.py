"""Offers behind the admin panel.

    POST /api/admin/sources/{id}/offers        submit one observation
    POST /api/admin/sources/{id}/offers/batch  submit many, gzipped
    GET  /api/admin/offers                 the listings
    GET  /api/admin/offers/{id}/raw        every observation of one
    GET  /api/admin/raw-offers/{id}/reading
    POST /api/admin/raw-offers/{id}/renormalize
    GET  /api/admin/offers/coverage        how far a deterministic matcher could get

Ingestion is a POST because there is no fetcher yet. That is the point rather than a
placeholder: a sample can be loaded by hand and measured before a line of crawling is
written, and the measurement is what decides what the matcher should be.
"""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import OfferServiceDep
from app.api.pagination import pagination_params
from app.features.offers.schemas import (
    OFFER_SORT,
    Availability,
    BatchResult,
    Condition,
    Coverage,
    IngestResult,
    MatchMethod,
    MatchState,
    NormalizedOfferRead,
    OfferRead,
    OfferTrace,
    QueueReason,
    RawOfferBatch,
    RawOfferIngest,
    RawOfferRead,
)
from app.schemas.common import ErrorResponse
from app.schemas.pagination import Page, Pagination

router = APIRouter(prefix="/offers", tags=["admin: offers"])
sources_router = APIRouter(prefix="/sources", tags=["admin: offers"])
raw_router = APIRouter(prefix="/raw-offers", tags=["admin: offers"])

PageParams = Annotated[Pagination, Depends(pagination_params())]
OfferPageParams = Annotated[
    Pagination, Depends(pagination_params(sortable=OFFER_SORT, default_sort="id"))
]


@sources_router.post(
    "/{source_id}/offers",
    response_model=IngestResult,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit one observation",
    responses={
        404: {"model": ErrorResponse, "description": "Source not found"},
        422: {"model": ErrorResponse, "description": "Unknown market, or seller not given"},
    },
)
async def ingest(source_id: int, payload: RawOfferIngest, service: OfferServiceDep) -> IngestResult:
    """The payload is stored verbatim and read afterwards.

    An unchanged page hashes to what is already on file, bumps a timestamp and writes
    nothing — `stored` comes back false. That is what keeps the raw table proportional to
    how much the world changes rather than to how often we look at it.
    """
    return await service.ingest(source_id, payload)


@sources_router.post(
    "/{source_id}/offers/batch",
    response_model=BatchResult,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit many observations",
    responses={
        404: {"model": ErrorResponse, "description": "Source or run not found"},
        422: {"model": ErrorResponse, "description": "Unknown market, or the batch is too large"},
    },
)
async def ingest_batch(
    source_id: int, batch: RawOfferBatch, service: OfferServiceDep
) -> BatchResult:
    """One request, one transaction, one audit entry.

    Post it with `Content-Encoding: gzip` — product JSON compresses by roughly an order of
    magnitude, and the difference is paid on every pass of every channel.

    Partial on purpose. One malformed card does not throw away the pass that collected the
    other eight hundred and ninety-nine; each failure comes back named, because a batch
    that reports "two failed" is a batch nobody can fix.
    """
    return await service.ingest_batch(source_id, batch)


@router.get("/coverage", response_model=Coverage, summary="How far determinism gets")
async def coverage(service: OfferServiceDep) -> Coverage:
    """The number everything else in the parser design is downstream of.

    A barcode is the strongest signal, brand with a part number the next, a brand alone
    narrows the field but decides nothing. If most readings land in the last bucket, the
    centre of the work is pulling identity out of free text rather than matching.
    """
    return await service.coverage()


@router.get("", response_model=Page[OfferRead], summary="List offers")
async def list_offers(
    service: OfferServiceDep,
    pagination: OfferPageParams,
    seller_id: Annotated[int | None, Query()] = None,
    market_code: Annotated[str | None, Query(max_length=2)] = None,
    shop_id: Annotated[list[int] | None, Query(description="Repeat for several")] = None,
    variant_id: Annotated[
        list[int] | None, Query(description="Placed on this entry. Repeat for several")
    ] = None,
    product_id: Annotated[
        list[int] | None,
        Query(description="Placed on an entry of this family. Repeat for several"),
    ] = None,
    condition: Annotated[Condition | None, Query()] = None,
    listed: Annotated[
        bool | None,
        Query(description="On sale now: seen by its channel's newest full pass that ended ok"),
    ] = None,
    match_state: Annotated[
        list[MatchState] | None,
        Query(
            description="`placed`; `queued` — the matcher could not decide; `unplaced` —"
            " neither. Repeat for several"
        ),
    ] = None,
    queue_reason: Annotated[
        list[QueueReason] | None, Query(description="Why it is queued. Repeat for several")
    ] = None,
    method: Annotated[
        list[MatchMethod] | None, Query(description="What placed it. Repeat for several")
    ] = None,
    availability: Annotated[
        list[Availability] | None, Query(description="Repeat for several")
    ] = None,
    brand_id: Annotated[
        list[int] | None,
        Query(description="The placed product's brand. Repeat for several"),
    ] = None,
    category_id: Annotated[
        list[int] | None,
        Query(
            description="The placed product's category, else what its channel collects."
            " Repeat for several"
        ),
    ] = None,
    price_min: Annotated[Decimal | None, Query(ge=0)] = None,
    price_max: Annotated[Decimal | None, Query(ge=0)] = None,
    search: Annotated[
        str | None,
        Query(max_length=200, description="Title or the shop's id contains; barcode equals"),
    ] = None,
) -> Page[OfferRead]:
    """A product card asks `product_id=…&listed=true&condition=new&sort=price`: who sells the
    thing new today, cheapest first. Review asks `match_state=queued&queue_reason=ambiguous`,
    or `method=brand_model` for the placements that rest on a model name alone."""
    items, total = await service.list_offers(
        pagination,
        seller_id=seller_id,
        market_code=market_code,
        shop_ids=shop_id,
        variant_ids=variant_id,
        product_ids=product_id,
        condition=condition.value if condition else None,
        listed=listed,
        match_states=[state.value for state in match_state or []],
        queue_reasons=[reason.value for reason in queue_reason or []],
        methods=[value.value for value in method or []],
        availabilities=[value.value for value in availability or []],
        brand_ids=brand_id,
        category_ids=category_id,
        price_min=price_min,
        price_max=price_max,
        search=search,
    )
    return Page[OfferRead].of(items, total, pagination)


@router.get(
    "/{offer_id}",
    response_model=OfferRead,
    summary="Get an offer",
    responses={404: {"model": ErrorResponse, "description": "Offer not found"}},
)
async def get_offer(offer_id: int, service: OfferServiceDep) -> OfferRead:
    return await service.get_offer(offer_id)


@router.get(
    "/{offer_id}/trace",
    response_model=OfferTrace,
    summary="One listing from the shop's bytes to the catalogue",
    responses={404: {"model": ErrorResponse, "description": "Offer not found"}},
)
async def trace_offer(offer_id: int, service: OfferServiceDep) -> OfferTrace:
    """The observation, the reading recomputed rule by rule with what each rule changed, the
    stored reading beside it, the match with its history, and the entry it is on. Writes
    nothing."""
    return await service.trace(offer_id)


@router.get(
    "/{offer_id}/raw",
    response_model=list[RawOfferRead],
    summary="Every observation of one listing",
)
async def list_observations(offer_id: int, service: OfferServiceDep) -> list[RawOfferRead]:
    """One row per distinct content, newest first — not one per fetch."""
    return await service.list_observations(offer_id)


@raw_router.get(
    "/{raw_offer_id}/reading",
    response_model=NormalizedOfferRead,
    summary="Our reading of one observation",
    responses={404: {"model": ErrorResponse, "description": "No reading under this ruleset"}},
)
async def get_reading(raw_offer_id: int, service: OfferServiceDep) -> NormalizedOfferRead:
    return await service.get_reading(raw_offer_id)


@raw_router.post(
    "/{raw_offer_id}/renormalize",
    response_model=NormalizedOfferRead,
    summary="Read stored bytes again",
    responses={404: {"model": ErrorResponse, "description": "Raw offer not found"}},
)
async def renormalize(raw_offer_id: int, service: OfferServiceDep) -> NormalizedOfferRead:
    """The property the pipeline exists for: a rule change is re-applied to what is already
    stored rather than re-crawled. Re-running the same ruleset is idempotent; a new version
    gets its own row, so the two readings can be compared instead of one replacing the
    other."""
    return await service.renormalize(raw_offer_id)
