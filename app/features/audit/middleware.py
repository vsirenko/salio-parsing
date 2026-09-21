"""Records one audit entry per admin request.

Middleware rather than a dependency for two reasons: a dependency cannot see the
status code the handler ended up returning, and middleware cannot be forgotten when
somebody adds a new admin route.
"""

import logging
from time import perf_counter
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

from app.core.audit import open_context
from app.core.net import client_ip
from app.features.audit.schemas import AuditEntryCreate
from app.features.audit.service import record_entry

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class AuditMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, path_prefix: str, trust_proxy_headers: bool) -> None:
        super().__init__(app)
        self.path_prefix = path_prefix
        self.trust_proxy_headers = trust_proxy_headers

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith(self.path_prefix):
            return await call_next(request)

        incoming = request.headers.get(REQUEST_ID_HEADER) if self.trust_proxy_headers else None
        context = open_context(incoming or uuid4().hex)

        started = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = context.request_id
            return response
        finally:
            entry = AuditEntryCreate(
                request_id=context.request_id,
                actor_id=context.actor_id,
                actor_email=context.actor_email,
                method=request.method,
                path=request.url.path,
                status_code=status_code,
                target_type=context.target_type,
                target_id=context.target_id,
                changes=context.changes or None,
                ip=client_ip(request, trust_proxy_headers=self.trust_proxy_headers),
                user_agent=request.headers.get("user-agent"),
                duration_ms=int((perf_counter() - started) * 1000),
            )
            try:
                await record_entry(entry)
            except Exception:
                # Never let bookkeeping break the request. If the audit trail becomes a
                # compliance requirement, fail closed here instead.
                logger.exception("Failed to write audit entry for %s", request.url.path)
