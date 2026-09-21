"""Health probes.

Two endpoints on purpose: an orchestrator restarts a container that fails liveness,
so liveness must not depend on the database — a database blip would otherwise turn
into a restart loop. Readiness is what takes the instance out of the load balancer.
"""

import logging

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.db.session import check_connection
from app.schemas.common import HealthResponse, ReadinessResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    responses={503: {"model": ReadinessResponse, "description": "A dependency is down"}},
)
async def ready() -> ReadinessResponse | JSONResponse:
    try:
        await check_connection()
    except Exception:
        logger.exception("Readiness check failed")
        body = ReadinessResponse(status="unavailable", database="down")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=body.model_dump()
        )

    return ReadinessResponse(status="ok", database="up")
