"""The judge behind the admin panel.

GET /api/admin/judge/verdicts   every answer bought, with what it was asked
GET /api/admin/judge/summary    what it cost over the last day, week and all time

Running the judge is not here. It belongs to whoever owns the work being judged — for
brands that is `POST /api/admin/matching/judge` — because deciding that a question is
worth asking is not this feature's business.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import JudgeServiceDep
from app.api.pagination import pagination_params
from app.features.judge.schemas import JudgeSummary, VerdictRead
from app.schemas.pagination import Page, Pagination

router = APIRouter(prefix="/judge", tags=["admin: judge"])

PageParams = Annotated[Pagination, Depends(pagination_params())]


@router.get("/verdicts", response_model=Page[VerdictRead], summary="What the judge answered")
async def verdicts(
    service: JudgeServiceDep,
    pagination: PageParams,
    kind: Annotated[str | None, Query(description="One kind of question")] = None,
) -> Page[VerdictRead]:
    """Newest first, each row carrying the state it was asked about and the full
    distribution that came back.

    Stored for the same reason a match keeps its evidence: an answer nobody can inspect
    can only be deleted, never argued with.
    """
    items, total = await service.verdicts(pagination, kind=kind)
    return Page[VerdictRead].of(items, total, pagination)


@router.get("/summary", response_model=JudgeSummary, summary="What the judge cost")
async def summary(service: JudgeServiceDep) -> JudgeSummary:
    """Questions bought and their tokens, and how many were answered from the store
    instead, over the last day, the last week and all time. Tokens, not money: the price
    is the provider's and would go stale here."""
    return await service.summary()
