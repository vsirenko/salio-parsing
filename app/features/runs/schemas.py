"""Run schemas: one execution of one channel, and what it earned the right to conclude."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Kind(StrEnum):
    """Two, and only two.

    A dedicated stock endpoint is not a third: it is another channel into the same shop
    whose full pass happens to carry availability and nothing else, which the channel
    model already covers.
    """

    FULL = "full"
    QUICK = "quick"


class Status(StrEnum):
    RUNNING = "running"
    # Finished, contract passed. The only status that earns the right to treat what was
    # not seen as gone.
    OK = "ok"
    # Finished, contract failed. What it saw is still written — those observations are
    # real. What it did not see means nothing.
    REJECTED = "rejected"
    FAILED = "failed"
    # Swept at scheduler startup rather than timed out: the scheduler is single by
    # construction, so anything still running when it starts is dead by definition.
    INTERRUPTED = "interrupted"


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    kind: Kind
    status: Status
    started_at: datetime
    finished_at: datetime | None
    items_seen: int
    items_ingested: int
    items_failed: int
    coverage: dict
    contract: dict
    error: str | None


class RunResult(BaseModel):
    """What a worker reports back when it is done."""

    model_config = ConfigDict(extra="forbid")

    items_seen: int = Field(ge=0)
    items_ingested: int = Field(ge=0)
    items_failed: int = Field(default=0, ge=0)
    # Measured per field: {"price": 0.99, "gtin": 0.68}. What the channel actually gave,
    # against what `delivers_*` says it is shaped to give.
    coverage: dict[str, float] = Field(default_factory=dict)
    # Set when the worker itself failed rather than the site being difficult.
    error: str | None = Field(default=None, max_length=4000)


class Check(BaseModel):
    """One contract test and what it found."""

    name: str
    passed: bool
    got: float | None = None
    limit: float | None = None
    note: str | None = None


class Due(BaseModel):
    """A channel and kind the scheduler should start now."""

    source_id: int
    kind: Kind
    due_at: datetime
