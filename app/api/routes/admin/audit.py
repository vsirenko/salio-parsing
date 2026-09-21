"""Audit trail, read-only: /api/admin/audit

There is no write, update or delete endpoint on purpose — entries are produced by the
middleware and nothing else.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import AuditServiceDep
from app.api.pagination import cursor_pagination_params
from app.schemas.audit import AuditEntry, Outcome
from app.schemas.pagination import Page, Pagination

router = APIRouter(prefix="/audit", tags=["admin: audit"])

# The trail is append-only and read newest-first, so it pages by cursor: offset would
# repeat rows as new entries arrive between requests.
PageParams = Annotated[
    Pagination, Depends(cursor_pagination_params(default_limit=50, max_limit=200))
]


@router.get("", response_model=Page[AuditEntry], summary="Read the audit trail")
async def list_audit_entries(
    audit: AuditServiceDep,
    pagination: PageParams,
    actor_id: Annotated[int | None, Query(description="Filter by the admin who acted")] = None,
    method: Annotated[str | None, Query(description="HTTP method, e.g. POST")] = None,
    path: Annotated[str | None, Query(description="Substring of the request path")] = None,
    outcome: Annotated[Outcome | None, Query(description="success or failure")] = None,
    since: Annotated[datetime | None, Query(description="Entries at or after this time")] = None,
    until: Annotated[datetime | None, Query(description="Entries at or before this time")] = None,
) -> Page[AuditEntry]:
    items, total = await audit.list_entries(
        pagination,
        actor_id=actor_id,
        method=method,
        path=path,
        outcome=outcome,
        since=since,
        until=until,
    )
    return Page[AuditEntry].of(items, total, pagination)
