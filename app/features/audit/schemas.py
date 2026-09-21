"""Audit trail schemas.

One record per admin request. The HTTP envelope is filled in automatically by the
middleware; the service layer adds the semantic part (what was touched, what changed).
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, computed_field


class Outcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


class AuditEntryCreate(BaseModel):
    request_id: str
    actor_id: int | None = None
    actor_email: str | None = None
    method: str
    path: str
    status_code: int
    target_type: str | None = None
    target_id: str | None = None
    changes: dict[str, Any] | None = None
    ip: str | None = None
    user_agent: str | None = None
    duration_ms: int

    @computed_field(description="Derived from the status code")
    @property
    def outcome(self) -> Outcome:
        return Outcome.SUCCESS if self.status_code < 400 else Outcome.FAILURE


class AuditEntry(AuditEntryCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
