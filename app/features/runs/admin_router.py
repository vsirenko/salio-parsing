"""Collection runs behind the admin panel.

GET  /api/admin/runs                    what has been collected, newest first
GET  /api/admin/runs/due                what the scheduler would start right now
GET  /api/admin/runs/{run_id}           one run, with its coverage and verdict
POST /api/admin/sources/{id}/runs       start one by hand
POST /api/admin/runs/{run_id}/finish    a worker reporting back
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import RunServiceDep
from app.api.pagination import pagination_params
from app.features.runs.schemas import Due, Kind, RunRead, RunResult, Status
from app.schemas.common import ErrorResponse
from app.schemas.pagination import Page, Pagination

router = APIRouter(prefix="/runs", tags=["admin: runs"])
sources_router = APIRouter(prefix="/sources", tags=["admin: runs"])

PageParams = Annotated[Pagination, Depends(pagination_params())]


@router.get("", response_model=Page[RunRead], summary="What has been collected")
async def runs(
    service: RunServiceDep,
    pagination: PageParams,
    source_id: Annotated[int | None, Query(description="One channel")] = None,
    run_status: Annotated[Status | None, Query(alias="status")] = None,
) -> Page[RunRead]:
    items, total = await service.runs(pagination, source_id=source_id, status=run_status)
    return Page[RunRead].of(items, total, pagination)


@router.get("/due", response_model=list[Due], summary="What the scheduler would start now")
async def due(service: RunServiceDep) -> list[Due]:
    """The scheduler's decision, without the scheduler.

    Everything it uses is an ordinary query over `runs` and `sources`, so what it would do
    can be read — and asserted — without starting a process.
    """
    return await service.due()


@router.get(
    "/{run_id}",
    response_model=RunRead,
    summary="One run",
    responses={404: {"model": ErrorResponse, "description": "Run not found"}},
)
async def run(run_id: int, service: RunServiceDep) -> RunRead:
    return await service.get(run_id)


@sources_router.post(
    "/{source_id}/runs",
    response_model=RunRead,
    status_code=status.HTTP_201_CREATED,
    summary="Start a run by hand",
    responses={
        404: {"model": ErrorResponse, "description": "Source not found"},
        409: {"model": ErrorResponse, "description": "One is already going"},
        422: {"model": ErrorResponse, "description": "This channel has no such pass"},
    },
)
async def start(source_id: int, kind: Kind, service: RunServiceDep) -> RunRead:
    """One live run per channel and kind, refused by the database rather than by the hope
    that only one scheduler exists."""
    return await service.start(source_id, kind)


@router.post(
    "/{run_id}/finish",
    response_model=RunRead,
    summary="A worker reporting back",
    responses={
        404: {"model": ErrorResponse, "description": "Run not found"},
        409: {"model": ErrorResponse, "description": "Already finished"},
    },
)
async def finish(run_id: int, result: RunResult, service: RunServiceDep) -> RunRead:
    """The contract is evaluated here, and it decides one thing: whether what this run did
    not see may be treated as gone. What it did see is written either way."""
    return await service.finish(run_id, result)
