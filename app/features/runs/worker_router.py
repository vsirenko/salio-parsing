"""What a collector may do with a run.

GET  /api/worker/runs/{run_id}         the job: what to collect, and how this channel works
POST /api/worker/runs/{run_id}/progress  what it has done so far
POST /api/worker/runs/{run_id}/finish  report back

Deliberately narrow. A worker cannot list runs, start one or look at anything else — the
scheduler decides what runs, and a parser processes hostile input all day.
"""

from fastapi import APIRouter

from app.api.deps import RunServiceDep
from app.features.runs.schemas import Job, RunProgress, RunRead, RunResult
from app.schemas.common import ErrorResponse

router = APIRouter(prefix="/runs", tags=["worker"])


@router.get(
    "/{run_id}",
    response_model=Job,
    summary="What this run is",
    responses={404: {"model": ErrorResponse, "description": "Run not found"}},
)
async def job(run_id: int, service: RunServiceDep) -> Job:
    """Everything needed to do the run, asked for rather than passed in on the command line.

    The channel's declaration comes with it: a worker has to know whether this pass is the
    full one or the cheap one, and which facts the cheap one is expected to bring back.
    """
    return await service.job(run_id)


@router.post(
    "/{run_id}/progress",
    status_code=204,
    summary="What this run has done so far",
    responses={
        404: {"model": ErrorResponse, "description": "Run not found"},
        409: {"model": ErrorResponse, "description": "Not running"},
    },
)
async def progress(run_id: int, progress: RunProgress, service: RunServiceDep) -> None:
    """Counts, for a person watching the run fill in. Only for the run's own row, only while
    it runs, and nothing in them is judged: the verdict is `finish`."""
    await service.report_progress(run_id, progress)


@router.post(
    "/{run_id}/finish",
    response_model=RunRead,
    summary="Report back",
    responses={
        404: {"model": ErrorResponse, "description": "Run not found"},
        409: {"model": ErrorResponse, "description": "Already finished"},
    },
)
async def finish(run_id: int, result: RunResult, service: RunServiceDep) -> RunRead:
    return await service.finish(run_id, result)
