"""Application entrypoint: `uvicorn app.main:app`."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin_router import admin_public_router, admin_router
from app.api.router import api_router
from app.api.worker_router import worker_public_router, worker_router
from app.core.compression import GzipRequestMiddleware
from app.core.config import settings
from app.core.error_handlers import register_error_handlers
from app.core.logging import configure_logging
from app.db.session import engine, session_factory
from app.features.audit.middleware import AuditMiddleware
from app.features.health.router import router as health_router
from app.features.users.service import seed_users

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting %s v%s (%s)", settings.app_name, settings.app_version, settings.environment
    )

    if settings.seed_users:
        async with session_factory() as session:
            created = await seed_users(session)
        logger.info("Seeded %d demo account(s)", created)

    yield

    # Return pooled connections instead of leaving them to time out.
    await engine.dispose()
    logger.info("Shutting down %s", settings.app_name)


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    # Added before CORS so it ends up inside it: CORS preflight is not an admin action.
    app.add_middleware(
        AuditMiddleware,
        path_prefix=f"{settings.api_prefix}/admin",
        trust_proxy_headers=settings.trust_proxy_headers,
    )

    # Added last, so it runs first: the body has to be readable before anything else
    # looks at it, the audit trail included.
    app.add_middleware(
        GzipRequestMiddleware, max_bytes=settings.max_decompressed_body_mb * 1024 * 1024
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.api_prefix)
    app.include_router(admin_public_router, prefix=settings.api_prefix)
    app.include_router(admin_router, prefix=settings.api_prefix)
    app.include_router(worker_public_router, prefix=settings.api_prefix)
    app.include_router(worker_router, prefix=settings.api_prefix)

    return app


app = create_app()
