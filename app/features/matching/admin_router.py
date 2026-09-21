"""Matching behind the admin panel.

POST   /api/admin/offers/{id}/match     run the ladder on one listing
PUT    /api/admin/offers/{id}/match     a human places it
DELETE /api/admin/offers/{id}/match     unlink, back to the queue
GET    /api/admin/offers/{id}/matches   every opinion ever held about it
POST   /api/admin/matching/run          work through what is unplaced
GET    /api/admin/match-queue           what could not be placed, and why
GET    /api/admin/match-queue/summary   the breakdown that says what to build next
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import MatchingServiceDep
from app.api.pagination import pagination_params
from app.features.matching.schemas import (
    ManualMatch,
    MatchOutcome,
    MatchQueueRead,
    OfferMatchRead,
    QueueSummary,
    Reason,
    RunReport,
)
from app.schemas.common import ErrorResponse
from app.schemas.pagination import Page, Pagination

offers_router = APIRouter(prefix="/offers", tags=["admin: matching"])
router = APIRouter(prefix="/matching", tags=["admin: matching"])
queue_router = APIRouter(prefix="/match-queue", tags=["admin: matching"])

PageParams = Annotated[Pagination, Depends(pagination_params())]


@offers_router.post(
    "/{offer_id}/match",
    response_model=MatchOutcome,
    summary="Run the ladder on one listing",
    responses={
        404: {"model": ErrorResponse, "description": "Offer not found"},
        422: {"model": ErrorResponse, "description": "Nothing has been read from it yet"},
    },
)
async def match_offer(offer_id: int, service: MatchingServiceDep) -> MatchOutcome:
    """Barcode, then brand with a part number, then brand with a model.

    Each rung is an index lookup rather than a scan. One hit is a match; several are
    `ambiguous`; none moves down a rung, and running out of rungs says exactly why.
    """
    return await service.match_offer(offer_id)


@offers_router.put(
    "/{offer_id}/match",
    response_model=MatchOutcome,
    summary="Place a listing by hand",
    responses={404: {"model": ErrorResponse, "description": "Offer or variant not found"}},
)
async def set_manually(
    offer_id: int, payload: ManualMatch, service: MatchingServiceDep
) -> MatchOutcome:
    """Supersedes whatever was thought before rather than overwriting it, so the previous
    opinion and its evidence survive."""
    return await service.set_manually(offer_id, payload)


@offers_router.delete(
    "/{offer_id}/match",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unlink a listing",
    responses={404: {"model": ErrorResponse, "description": "No active match"}},
)
async def unlink(offer_id: int, service: MatchingServiceDep) -> Response:
    await service.unlink(offer_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@offers_router.get(
    "/{offer_id}/matches",
    response_model=list[OfferMatchRead],
    summary="Every opinion held about one listing",
)
async def history(offer_id: int, service: MatchingServiceDep) -> list[OfferMatchRead]:
    """Newest first. A superseded row is kept on purpose: a link that turned out wrong is
    worth more as a record than as a deletion."""
    return await service.history(offer_id)


@router.post("/run", response_model=RunReport, summary="Work through what is unplaced")
async def run(
    service: MatchingServiceDep,
    limit: Annotated[int, Query(ge=1, le=1000, description="How many to attempt")] = 100,
) -> RunReport:
    """Skips listings that already have a live match, retries queued ones — the catalogue
    they failed against changes underneath them."""
    return await service.run(limit=limit)


@queue_router.get("/summary", response_model=QueueSummary, summary="What is in the way")
async def summary(service: MatchingServiceDep) -> QueueSummary:
    """The breakdown that decides what to build next.

    Mostly `signals_unmatched` means the work is creating variants. `brand_unresolved`
    means brand aliases. `no_signals` means pulling identity out of titles. `ambiguous` is
    the only bucket a pair judge can help with — and if it is nearly empty, a judge is not
    what this needs.
    """
    return await service.summary()


@queue_router.get("", response_model=Page[MatchQueueRead], summary="What could not be placed")
async def queue(
    service: MatchingServiceDep,
    pagination: PageParams,
    reason: Annotated[Reason | None, Query(description="One kind of problem")] = None,
) -> Page[MatchQueueRead]:
    """Each row carries the near misses that were considered, so deciding is a choice
    rather than a search."""
    items, total = await service.queue(pagination, reason=reason)
    return Page[MatchQueueRead].of(items, total, pagination)
