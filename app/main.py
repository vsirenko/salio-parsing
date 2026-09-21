"""Application entrypoint: `uvicorn app.main:app`."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin_router import admin_public_router, admin_router
from app.api.router import api_router
from app.api.routes import health
from app.core.audit_middleware import AuditMiddleware
from app.core.config import settings
from app.core.error_handlers import register_error_handlers
from app.core.logging import configure_logging
from app.services.audit import audit_service

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: open DB pools / warm caches here.
    logger.info(
        "Starting %s v%s (%s)", settings.app_name, settings.app_version, settings.environment
    )
    yield
    # Shutdown: close what you opened above.
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

    # Shared by the audit middleware and the audit routes.
    app.state.audit_service = audit_service

    # Added before CORS so it ends up inside it: CORS preflight is not an admin action.
    app.add_middleware(
        AuditMiddleware,
        path_prefix=f"{settings.api_prefix}/admin",
        trust_proxy_headers=settings.trust_proxy_headers,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    app.include_router(health.router)
    app.include_router(api_router, prefix=settings.api_prefix)
    app.include_router(admin_public_router, prefix=settings.api_prefix)
    app.include_router(admin_router, prefix=settings.api_prefix)

    return app


app = create_app()
