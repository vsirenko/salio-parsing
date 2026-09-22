"""Matching behind the admin panel.

POST   /api/admin/offers/{id}/match     run the ladder on one listing
PUT    /api/admin/offers/{id}/match     a human places it
DELETE /api/admin/offers/{id}/match     unlink, back to the queue
GET    /api/admin/offers/{id}/matches   every opinion ever held about it
POST   /api/admin/matching/run          work through what is unplaced
GET    /api/admin/match-queue           what could not be placed, and why
GET    /api/admin/match-queue/summary   the breakdown that says what to build next
POST   /api/admin/matching/judge        ask the judge about the brand choices, then retry
POST   /api/admin/offers/{id}/promote   make the variant this listing was looking for
POST   /api/admin/matching/promote      do that for everything identifiable in the queue
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import MatchingServiceDep
from app.api.pagination import pagination_params
from app.features.judge.schemas import JudgeReport
from app.features.matching.schemas import (
    ManualMatch,
    MatchOutcome,
    MatchQueueRead,
    MergeReport,
    OfferMatchRead,
    PromotionReport,
    QueueSummary,
    Reason,
    RenameReport,
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


@offers_router.post(
    "/{offer_id}/promote",
    response_model=MatchOutcome,
    summary="Make the variant this listing was looking for",
    responses={
        404: {"model": ErrorResponse, "description": "Offer not found"},
        422: {"model": ErrorResponse, "description": "Not enough to build a variant from"},
    },
)
async def promote(offer_id: int, service: MatchingServiceDep) -> MatchOutcome:
    """The catalogue has to start somewhere, and only the shops know what is in them.

    Deliberately not a new kind of match: the variant is created and then the ordinary
    ladder runs, so the link records the rung that actually fired rather than a method
    meaning "we made this from itself". Where the variant came from is in the audit trail.
    """
    return await service.promote(offer_id)


@router.post(
    "/promote",
    response_model=PromotionReport,
    summary="Start the catalogue from what can be identified",
)
async def promote_queue(
    service: MatchingServiceDep,
    limit: Annotated[int, Query(ge=1, le=1000, description="How many to consider")] = 100,
) -> PromotionReport:
    """Takes only listings that carry a barcode and come from a channel we trust.

    A variant made from a junk listing cannot afterwards be told from a real one, so the
    rest stay queued where somebody can look at them. Each candidate is matched before it
    is promoted, because the one before it may have just created the variant it needed.
    """
    return await service.promote_queue(limit=limit)


@router.post(
    "/merge",
    response_model=MergeReport,
    summary="Fold together the entries a barcode says are one product",
)
async def merge_duplicates(
    service: MatchingServiceDep,
    limit: Annotated[int, Query(ge=1, le=500, description="How many pairs to consider")] = 100,
) -> MergeReport:
    """Only a barcode decides. A part number names a family as often as a product, so two
    entries sharing one are usually two real configurations rather than one written twice."""
    return await service.merge_duplicates(limit=limit)


@router.post(
    "/rebuild",
    response_model=RenameReport,
    summary="Rebuild the entries named after a reading that has since changed",
)
async def rebuild_stale(
    service: MatchingServiceDep,
    limit: Annotated[int, Query(ge=1, le=500, description="How many to consider")] = 100,
) -> RenameReport:
    """Only an entry with one listing on it. Two shops agreeing on an entry is evidence its
    name is good enough, and one of them disagreeing about a `5G` suffix is not a reason to
    rename what they share."""
    return await service.rebuild_named_from_a_stale_reading(limit=limit)


@router.post(
    "/judge/ambiguous",
    response_model=JudgeReport,
    summary="Ask the judge which entry a listing is",
)
async def judge_ambiguous(
    service: MatchingServiceDep,
    limit: Annotated[int, Query(ge=1, le=200, description="How many to ask about")] = 50,
) -> JudgeReport:
    """Only `ambiguous`, and only after the corpus has been asked and could not answer: a
    marketing colour belongs to a maker, and no global registry row can hold it."""
    return await service.judge_ambiguous(limit=limit)


@router.post(
    "/judge",
    response_model=JudgeReport,
    summary="Ask the judge about the brand choices",
    responses={422: {"model": ErrorResponse, "description": "No TypeSafe API key configured"}},
)
async def judge_brands(
    service: MatchingServiceDep,
    limit: Annotated[int, Query(ge=1, le=500, description="How many to ask about")] = 50,
) -> JudgeReport:
    """Works `brand_ambiguous` and nothing else: it is the bucket that arrives with its
    options already in hand, and choosing between options is the only thing the judge does.

    A question already answered is not asked again, so running this twice costs nothing the
    second time. Answers below the confidence threshold are recorded and not acted on.
    """
    return await service.judge_brands(limit=limit)


@queue_router.get("/summary", response_model=QueueSummary, summary="What is in the way")
async def summary(service: MatchingServiceDep) -> QueueSummary:
    """The breakdown that decides what to build next.

    Mostly `signals_unmatched` means the work is creating variants. `brand_unknown` means
    reading raw strings and naming the brand behind them; `no_signals` means pulling
    identity out of titles. `brand_ambiguous` and `ambiguous` are the buckets that already
    carry their candidates, so they are the two a pair judge can help with — and if both are
    nearly empty, a judge is not what this needs.
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
