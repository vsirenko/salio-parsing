"""Collection runs behind the admin panel.

GET  /api/admin/runs                    what has been collected, newest first
GET  /api/admin/runs/due                what the scheduler would start right now
GET  /api/admin/runs/{run_id}           one run, with its coverage and verdict
GET  /api/admin/runs/{run_id}/failures  the products it could not bring in, and why
POST /api/admin/runs/{run_id}/cancel    stop one that is queued or working
POST /api/admin/sources/{id}/runs       start one by hand
POST /api/admin/runs/{run_id}/finish    a worker reporting back
GET  /api/admin/scheduler               alive or not, what runs, what is due, every next slot
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import RunServiceDep
from app.api.pagination import pagination_params
from app.features.runs.schemas import (
    RUN_SORT,
    Due,
    Kind,
    ReparseReport,
    ReparseRequest,
    RunFailures,
    RunRead,
    RunResult,
    SchedulerStatus,
    Status,
)
from app.schemas.common import ErrorResponse
from app.schemas.pagination import Page, Pagination

router = APIRouter(prefix="/runs", tags=["admin: runs"])
sources_router = APIRouter(prefix="/sources", tags=["admin: runs"])
scheduler_router = APIRouter(prefix="/scheduler", tags=["admin: runs"])

RunPageParams = Annotated[
    Pagination, Depends(pagination_params(sortable=RUN_SORT, default_sort="-started_at"))
]


@router.get("", response_model=Page[RunRead], summary="What has been collected")
async def runs(
    service: RunServiceDep,
    pagination: RunPageParams,
    source_id: Annotated[list[int] | None, Query(description="Repeat for several")] = None,
    shop_id: Annotated[list[int] | None, Query(description="Repeat for several")] = None,
    kind: Annotated[list[Kind] | None, Query(description="Repeat for several")] = None,
    run_status: Annotated[
        list[Status] | None, Query(alias="status", description="Repeat for several")
    ] = None,
    started_from: Annotated[datetime | None, Query()] = None,
    started_to: Annotated[datetime | None, Query(description="Before this moment")] = None,
) -> Page[RunRead]:
    """Newest first by default; `sort=-duration` or `sort=-items_seen` for the others. A
    channel's history to compare is `source_id=…&kind=full&limit=20`: each row carries its
    coverage, its counts and its verdict."""
    items, total = await service.runs(
        pagination,
        source_ids=source_id,
        shop_ids=shop_id,
        kinds=[value.value for value in kind or []],
        statuses=[value.value for value in run_status or []],
        started_from=started_from,
        started_to=started_to,
    )
    return Page[RunRead].of(items, total, pagination)


@router.get("/due", response_model=list[Due], summary="What the scheduler would start now")
async def due(service: RunServiceDep) -> list[Due]:
    """The scheduler's decision, without the scheduler.

    Everything it uses is an ordinary query over `runs` and `sources`, so what it would do
    can be read — and asserted — without starting a process.
    """
    return await service.due()


@router.get(
    "/{run_id}/failures",
    response_model=RunFailures,
    summary="The products a run could not bring in, and why",
    responses={404: {"model": ErrorResponse, "description": "Run not found"}},
)
async def failures(
    run_id: int,
    service: RunServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> RunFailures:
    """A sample the worker kept — up to two hundred — each with its stage (`fetch`,
    `parse`, `ingest`), the shop's id for the product, its link and the reason, beside the
    full count. A `parse` failure's bytes are in the snapshot store's `failed/` area. A run
    killed rather than finished, and runs from before the sample was kept, have none."""
    return await service.failures(run_id, limit=limit)


@router.post(
    "/reparse",
    response_model=ReparseReport,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Read a category's or a brand's channels again",
    responses={
        404: {"model": ErrorResponse, "description": "Category or brand not found"},
        422: {"model": ErrorResponse, "description": "Neither a category nor a brand"},
    },
)
async def queue_reparses(payload: ReparseRequest, service: RunServiceDep) -> ReparseReport:
    """What follows registry work: a word entered reaches no stored reading until the
    snapshots are read again. One reparse is queued per channel that has collected anything,
    on the schedule or off it, and each is settled when it ends — rebuild, match, promote —
    as any reparse is. Follow them through `GET /api/admin/runs/{run_id}`."""
    return await service.queue_reparses(payload)


@router.post(
    "/{run_id}/cancel",
    response_model=RunRead,
    summary="Stop a run that is queued or working",
    responses={
        404: {"model": ErrorResponse, "description": "Run not found"},
        409: {"model": ErrorResponse, "description": "Already finished"},
    },
)
async def cancel(run_id: int, service: RunServiceDep) -> RunRead:
    """Closed at once as `cancelled`, which frees the channel's slot; the scheduler kills
    the worker behind it on its next tick, and anything that worker hands over meanwhile is
    refused. Like every end but `ok`, it concludes nothing about what it did not see."""
    return await service.cancel(run_id)


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
    """Queued: the scheduler's next tick gives it a worker, ahead of anything scheduled.
    One live run per channel and kind — queued or running — refused by the database rather
    than by the hope that only one scheduler exists."""
    return await service.start(source_id, kind, queued=True)


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


@scheduler_router.get(
    "", response_model=SchedulerStatus, summary="The scheduler, and every channel's schedule"
)
async def scheduler_status(service: RunServiceDep) -> SchedulerStatus:
    """Whether the scheduler ticked within three ticks, what is running, what is due now, and
    for every channel its schedule, its last run and its next slot, computed from the cron."""
    return await service.status()
