"""Audit trail storage.

Append-only by design: there is no update and no delete, and no endpoint exposes one.
The database user that runs this in production should hold INSERT and SELECT only.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditEntry as AuditEntryRow
from app.db.query import paginated
from app.db.session import session_factory
from app.features.audit.schemas import AuditEntry, AuditEntryCreate, Outcome
from app.schemas.pagination import Pagination

# status >= 400 is a failure; expressed here so the filter can run in SQL.
FAILURE_FROM = 400
# The methods that only read. Everything else is an attempt to change something.
READS = ("GET", "HEAD", "OPTIONS")


async def record_entry(payload: AuditEntryCreate) -> None:
    """Write one entry in its own transaction.

    Deliberately not the request session: when a request fails its transaction is
    rolled back, and the record of that failure must not be rolled back with it.
    """
    async with session_factory() as session:
        session.add(AuditEntryRow(**payload.model_dump(exclude={"outcome"})))
        await session.commit()


class AuditService:
    """Read side. Writes go through `record_entry` above."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_entries(
        self,
        pagination: Pagination,
        *,
        actor_id: int | None = None,
        methods: list[str] | None = None,
        writes: bool | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        path: str | None = None,
        outcome: Outcome | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[list[AuditEntry], int]:
        stmt = select(AuditEntryRow)

        # Cursor: everything written before the anchor. Applied like any other filter,
        # so `total` stays consistent with what the caller asked for.
        if pagination.before_id is not None:
            stmt = stmt.where(AuditEntryRow.id < pagination.before_id)
        if actor_id is not None:
            stmt = stmt.where(AuditEntryRow.actor_id == actor_id)
        if methods:
            stmt = stmt.where(AuditEntryRow.method.in_([m.upper() for m in methods]))
        if writes is True:
            stmt = stmt.where(AuditEntryRow.method.not_in(READS))
        elif writes is False:
            stmt = stmt.where(AuditEntryRow.method.in_(READS))
        if target_type:
            stmt = stmt.where(AuditEntryRow.target_type == target_type)
        if target_id:
            stmt = stmt.where(AuditEntryRow.target_id == target_id)
        if path:
            stmt = stmt.where(AuditEntryRow.path.contains(path))
        if outcome is Outcome.SUCCESS:
            stmt = stmt.where(AuditEntryRow.status_code < FAILURE_FROM)
        elif outcome is Outcome.FAILURE:
            stmt = stmt.where(AuditEntryRow.status_code >= FAILURE_FROM)
        if since is not None:
            stmt = stmt.where(AuditEntryRow.created_at >= since)
        if until is not None:
            stmt = stmt.where(AuditEntryRow.created_at <= until)

        # Newest first: an audit trail is read from the most recent event backwards.
        rows, total = await paginated(
            self.session, stmt.order_by(AuditEntryRow.id.desc()), pagination
        )
        return [AuditEntry.model_validate(row) for row in rows], total
