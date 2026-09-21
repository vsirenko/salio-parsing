"""Audit trail storage.

Append-only by design: there is no update and no delete, and no endpoint exposes one.
In a real deployment this is a separate table whose DB user holds INSERT and SELECT
grants only.
"""

import asyncio
from datetime import UTC, datetime

from app.schemas.audit import AuditEntry, AuditEntryCreate, Outcome
from app.schemas.pagination import Pagination


class AuditService:
    def __init__(self) -> None:
        self._items: dict[int, AuditEntry] = {}
        self._next_id = 1
        self._lock = asyncio.Lock()

    async def record(self, payload: AuditEntryCreate) -> AuditEntry:
        async with self._lock:
            entry = AuditEntry(
                id=self._next_id,
                created_at=datetime.now(UTC),
                # outcome is computed, not stored.
                **payload.model_dump(exclude={"outcome"}),
            )
            self._items[entry.id] = entry
            self._next_id += 1
            return entry

    async def list_entries(
        self,
        pagination: Pagination,
        *,
        actor_id: int | None = None,
        method: str | None = None,
        path: str | None = None,
        outcome: Outcome | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[list[AuditEntry], int]:
        items = list(self._items.values())

        # Cursor: everything written before the anchor. Applied like any other filter,
        # so `total` stays consistent with what the caller asked for.
        if pagination.before_id is not None:
            items = [e for e in items if e.id < pagination.before_id]
        if actor_id is not None:
            items = [e for e in items if e.actor_id == actor_id]
        if method:
            items = [e for e in items if e.method == method.upper()]
        if path:
            items = [e for e in items if path in e.path]
        if outcome is not None:
            items = [e for e in items if e.outcome is outcome]
        if since is not None:
            items = [e for e in items if e.created_at >= since]
        if until is not None:
            items = [e for e in items if e.created_at <= until]

        # Newest first: an audit trail is read from the most recent event backwards.
        items.sort(key=lambda e: e.id, reverse=True)
        return pagination.slice(items), len(items)


audit_service = AuditService()
