"""Audit trail, read-only: /api/admin/audit

There is no write, update or delete endpoint on purpose — entries are produced by the
middleware and nothing else.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AuditServiceDep
from app.schemas.audit import AuditEntry, Outcome
from app.schemas.common import Page

router = APIRouter(prefix="/audit", tags=["admin: audit"])


@router.get("", response_model=Page[AuditEntry], summary="Read the audit trail")
async def list_audit_entries(
    audit: AuditServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    actor_id: Annotated[int | None, Query(description="Filter by the admin who acted")] = None,
    method: Annotated[str | None, Query(description="HTTP method, e.g. POST")] = None,
    path: Annotated[str | None, Query(description="Substring of the request path")] = None,
    outcome: Annotated[Outcome | None, Query(description="success or failure")] = None,
    since: Annotated[datetime | None, Query(description="Entries at or after this time")] = None,
    until: Annotated[datetime | None, Query(description="Entries at or before this time")] = None,
) -> Page[AuditEntry]:
    items, total = await audit.list_entries(
        limit=limit,
        offset=offset,
        actor_id=actor_id,
        method=method,
        path=path,
        outcome=outcome,
        since=since,
        until=until,
    )
    return Page[AuditEntry](items=items, total=total, limit=limit, offset=offset)
