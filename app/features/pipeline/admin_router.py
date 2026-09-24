"""The pipeline, counted, behind the admin panel.

GET /api/admin/pipeline                 every step from a channel to the catalogue
GET /api/admin/pipeline/runs/{run_id}   one run through the same steps, as it goes
GET /api/admin/pipeline/history          the key numbers as they stood, day by day
"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import PipelineServiceDep
from app.features.pipeline.schemas import Pipeline, PipelineDay, RunFlow
from app.schemas.common import ErrorResponse

router = APIRouter(prefix="/pipeline", tags=["admin: pipeline"])


@router.get(
    "",
    response_model=Pipeline,
    summary="Every step from a channel to the catalogue, counted",
    responses={404: {"model": ErrorResponse, "description": "No such category or source"}},
)
async def pipeline(
    service: PipelineServiceDep,
    category: Annotated[str | None, Query(description="A category slug, `tablets`")] = None,
    source: Annotated[str | None, Query(description="A source slug, `bigbox-tablets`")] = None,
) -> Pipeline:
    """The nodes from the channels to the catalogue with how many listings reached each and
    what they are made of, the edges between them, and every channel's own pass."""
    return await service.summary(category=category, source=source)


@router.get(
    "/history",
    response_model=list[PipelineDay],
    summary="The key numbers as they stood, day by day",
)
async def history(
    service: PipelineServiceDep,
    days: Annotated[int, Query(ge=1, le=366)] = 30,
    scope: Annotated[str, Query(max_length=64, description="`all`, or a category slug")] = "all",
) -> list[PipelineDay]:
    """One row a day, kept by the scheduler — everything else here is counted as it is now,
    and yesterday cannot be recomputed. Days it was not running are missing, not zero."""
    return await service.history(days=days, scope=scope)


@router.get(
    "/runs/{run_id}",
    response_model=RunFlow,
    summary="One run through the pipeline, filling in as it goes",
    responses={404: {"model": ErrorResponse, "description": "Run not found"}},
)
async def run_flow(run_id: int, service: PipelineServiceDep) -> RunFlow:
    """What the worker reported so far, what became of the listings this run saw, and what
    settling it placed. Poll it while the run is open to watch the nodes fill in."""
    return await service.run(run_id)
