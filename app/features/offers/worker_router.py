"""What a collector may do with offers: hand over what it crawled, and nothing else.

POST /api/worker/sources/{source_id}/offers/batch

No audit entry is written here, unlike the same call on the admin router. That is not an
oversight: the trail records what an administrator did, and a scheduled crawl is not that.
What a run collected is recorded on the run.
"""

from fastapi import APIRouter, status

from app.api.deps import OfferServiceDep
from app.features.offers.schemas import BatchResult, RawOfferBatch
from app.schemas.common import ErrorResponse

router = APIRouter(prefix="/sources", tags=["worker"])


@router.post(
    "/{source_id}/offers/batch",
    response_model=BatchResult,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Hand over a pass",
    responses={
        404: {"model": ErrorResponse, "description": "Source or run not found"},
        422: {"model": ErrorResponse, "description": "Unknown market, or the batch is too large"},
    },
)
async def ingest_batch(
    source_id: int, batch: RawOfferBatch, service: OfferServiceDep
) -> BatchResult:
    """Post it with `Content-Encoding: gzip`."""
    return await service.ingest_batch(source_id, batch)
