"""The judge behind the admin panel.

GET    /api/admin/judge/config                   whether it can be asked, and its thresholds
GET    /api/admin/judge/verdicts                 every answer bought, named and filterable
GET    /api/admin/judge/verdicts/{id}            one answer
DELETE /api/admin/judge/verdicts/{id}            forget it, so the next pass asks again
POST   /api/admin/judge/verdicts/{id}/review     a person's word on it
GET    /api/admin/judge/calibration              confidence against those words
GET    /api/admin/judge/usage                    what was bought, day by day
GET    /api/admin/judge/summary                  what it cost over a day, a week, all time

Running the judge is not here. It belongs to whoever owns the work being judged — for
brands that is `POST /api/admin/matching/judge` — because deciding that a question is
worth asking is not this feature's business.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import CurrentAdmin, JudgeServiceDep
from app.api.pagination import pagination_params
from app.features.judge.schemas import (
    VERDICT_SORT,
    Calibration,
    JudgeConfig,
    JudgeSummary,
    Kind,
    Outcome,
    ReviewCreate,
    UsageDay,
    VerdictRead,
)
from app.schemas.common import ErrorResponse
from app.schemas.pagination import Page, Pagination

router = APIRouter(prefix="/judge", tags=["admin: judge"])

VerdictPageParams = Annotated[
    Pagination, Depends(pagination_params(sortable=VERDICT_SORT, default_sort="-created_at"))
]


@router.get("/config", response_model=JudgeConfig, summary="Whether the judge can be asked")
async def config(service: JudgeServiceDep) -> JudgeConfig:
    """`enabled` is whether a key is configured: without one every pass answers 422
    `judge_disabled`, so a page can say the judge is off instead of offering buttons."""
    return service.config()


@router.get("/verdicts", response_model=Page[VerdictRead], summary="What the judge answered")
async def verdicts(
    service: JudgeServiceDep,
    pagination: VerdictPageParams,
    kind: Annotated[list[Kind] | None, Query(description="Repeat for several")] = None,
    outcome: Annotated[list[Outcome] | None, Query(description="Repeat for several")] = None,
    no_match: Annotated[
        bool | None, Query(description='Answered, or did not answer, "none of these"')
    ] = None,
    confidence_min: Annotated[Decimal | None, Query(ge=0, le=1)] = None,
    confidence_max: Annotated[Decimal | None, Query(ge=0, le=1)] = None,
    search: Annotated[
        str | None, Query(max_length=200, description="The listing's title contains")
    ] = None,
    created_from: Annotated[datetime | None, Query()] = None,
    created_to: Annotated[datetime | None, Query(description="Before this moment")] = None,
    forgotten: Annotated[bool | None, Query()] = None,
) -> Page[VerdictRead]:
    """Newest first by default. Each answer carries its options named, the listings it
    was about and where they stand now, what policy made of it, and a person's review.

    Stored for the same reason a match keeps its evidence: an answer nobody can inspect
    can only be deleted, never argued with.
    """
    items, total = await service.verdicts(
        pagination,
        kinds=[value.value for value in kind or []],
        outcomes=[value.value for value in outcome or []],
        no_match=no_match,
        confidence_min=confidence_min,
        confidence_max=confidence_max,
        search=search,
        created_from=created_from,
        created_to=created_to,
        forgotten=forgotten,
    )
    return Page[VerdictRead].of(items, total, pagination)


@router.get(
    "/verdicts/{verdict_id}",
    response_model=VerdictRead,
    summary="One answer",
    responses={404: {"model": ErrorResponse, "description": "Verdict not found"}},
)
async def verdict(verdict_id: int, service: JudgeServiceDep) -> VerdictRead:
    return await service.verdict(verdict_id)


@router.delete(
    "/verdicts/{verdict_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Forget an answer, so the next pass asks again",
    responses={404: {"model": ErrorResponse, "description": "Verdict not found"}},
)
async def forget(verdict_id: int, service: JudgeServiceDep) -> Response:
    """Kept and marked `forgotten_at`, not deleted: the store stops answering with it,
    and what it cost stays counted. A listing it already placed stays placed — that match
    is its own record."""
    await service.forget(verdict_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/verdicts/{verdict_id}/review",
    response_model=VerdictRead,
    summary="Say whether an answer was right",
    responses={404: {"model": ErrorResponse, "description": "Verdict not found"}},
)
async def review(
    verdict_id: int, payload: ReviewCreate, current: CurrentAdmin, service: JudgeServiceDep
) -> VerdictRead:
    """One word per answer, the latest standing. What `GET /calibration` counts."""
    return await service.review(verdict_id, payload, reviewer_id=current.id)


@router.get("/calibration", response_model=Calibration, summary="Confidence against reviews")
async def calibration(
    service: JudgeServiceDep,
    kind: Annotated[Kind | None, Query()] = None,
    buckets: Annotated[int, Query(ge=2, le=50)] = 10,
) -> Calibration:
    """Answers in equal buckets of the number the threshold is on — `confidence`, or for
    the model check the probability of `same` — each with how many a person marked right
    and wrong. Where the threshold should sit is read off this."""
    return await service.calibration(kind.value if kind else None, buckets=buckets)


@router.get("/usage", response_model=list[UsageDay], summary="What was bought, day by day")
async def usage(
    service: JudgeServiceDep, days: Annotated[int, Query(ge=1, le=366)] = 30
) -> list[UsageDay]:
    """Per day and kind: answers bought, their tokens, and answers the store gave instead.
    Days with nothing are left out."""
    return await service.usage(days=days)


@router.get("/summary", response_model=JudgeSummary, summary="What the judge cost")
async def summary(service: JudgeServiceDep) -> JudgeSummary:
    """Questions bought and their tokens, and how many were answered from the store
    instead, over the last day, the last week and all time. Tokens, not money: the price
    is the provider's and would go stale here."""
    return await service.summary()
