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

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import OfferServiceDep
from app.api.pagination import pagination_params
from app.features.offers.schemas import (
    BatchResult,
    Coverage,
    IngestResult,
    NormalizedOfferRead,
    OfferRead,
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
    pagination: PageParams,
    seller_id: Annotated[int | None, Query()] = None,
    market_code: Annotated[str | None, Query(max_length=2)] = None,
) -> Page[OfferRead]:
    items, total = await service.list_offers(
        pagination, seller_id=seller_id, market_code=market_code
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
