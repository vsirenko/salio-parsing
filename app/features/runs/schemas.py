"""Run schemas: one execution of one channel, and what it earned the right to conclude."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Kind(StrEnum):
    """Two that collect, and one that does not.

    A dedicated stock endpoint is not a fourth: it is another channel into the same shop
    whose full pass happens to carry availability and nothing else, which the channel
    model already covers.
    """

    FULL = "full"
    QUICK = "quick"
    # Re-reads the bytes already on disk with the parser as it is now. No network, no
    # schedule — started by hand, after a parser is changed, to find out whether the change
    # helped. It is the only way a parser fix can be judged without crawling a shop again.
    REPARSE = "reparse"


class Status(StrEnum):
    RUNNING = "running"
    # Finished, contract passed. Together with a collecting kind, the only thing that earns
    # the right to treat what was not seen as gone — a reparse sees whatever happens to be
    # in the snapshot store, so its absences mean nothing at all.
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


class Job(BaseModel):
    """Everything a collector needs to do one run.

    Asked for rather than passed on a command line: the channel's declaration comes with
    it, because a worker has to know whether this pass is the full one or the cheap one,
    and which facts the cheap one is expected to bring back.
    """

    run_id: int
    source_id: int
    source_slug: str
    kind: Kind
    access: str
    decode: str
    base_url: str | None
    market_codes: list[str]
    # What this particular pass is expected to bring back — `delivers_full` or
    # `delivers_quick`, already chosen by `kind` so the worker does not choose wrongly.
    delivers: list[str]


class Due(BaseModel):
    """A channel and kind the scheduler should start now."""

    source_id: int
    kind: Kind
    due_at: datetime
