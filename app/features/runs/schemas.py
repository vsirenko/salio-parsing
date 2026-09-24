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
    # Asked for by hand, and waiting for the scheduler to give it a worker on its next tick.
    # A run started from the panel used to be created running with nothing behind it, and
    # sat there until the next startup swept it: nobody spawns a worker for a row.
    QUEUED = "queued"
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


class ChannelSchedule(BaseModel):
    """One channel as the scheduler sees it: its schedule, its last run, its next slot.

    The next slot is computed on read from the cron and never stored, for the reason `runs`
    has no `next_run_at`: a stored one goes stale the moment somebody edits the schedule.
    """

    source_id: int
    source: str
    shop: str
    category: str | None
    is_enabled: bool
    # Whether the channel has a cheap pass at all. One that delivers nothing cheaply — 1a's
    # index, bm's GraphQL — refuses a `quick` run, and a panel should not offer one.
    has_quick: bool
    cron_full: str | None
    cron_quick: str | None
    next_full_at: datetime | None
    next_quick_at: datetime | None
    last_run: RunRead | None


class SchedulerStatus(BaseModel):
    """Whether the scheduler is alive, and what it is doing and will do.

    `alive` is a heartbeat fresher than three ticks. Nothing else can say it: a scheduler
    with nothing due is as quiet as one that has stopped.
    """

    alive: bool
    started_at: datetime | None
    ticked_at: datetime | None
    pid: int | None
    tick_seconds: int
    queued: list[RunRead]
    running: list[RunRead]
    due: list[Due]
    channels: list[ChannelSchedule]
