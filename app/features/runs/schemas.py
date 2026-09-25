"""Run schemas: one execution of one channel, and what it earned the right to conclude."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    # A person stopped it from the panel, queued or running. Like every end but `ok`, it
    # concludes nothing about what it did not see.
    CANCELLED = "cancelled"


RUN_SORT = ("id", "started_at", "duration", "items_seen")


class Named(BaseModel):
    id: int
    name: str


class SourceRef(BaseModel):
    id: int
    slug: str


class ReparseRequest(BaseModel):
    """Which channels to read again: a category's, a brand's, or a brand's in one category.

    At least one of the two. The whole of a channel is read either way — a reparse re-reads
    snapshots, and a brand is not a thing a snapshot is stored by — so a brand only narrows
    which channels, to those whose readings have named it."""

    model_config = ConfigDict(extra="forbid")

    category_id: int | None = None
    brand_id: int | None = None

    @model_validator(mode="after")
    def _something(self) -> "ReparseRequest":
        if self.category_id is None and self.brand_id is None:
            raise ValueError("name a category_id, a brand_id or both")
        return self


class QueuedReparse(BaseModel):
    source: SourceRef
    run_id: int


class ReparseReport(BaseModel):
    """The runs queued, one per channel, and the channels already being read again — a
    second reparse of those would be refused by the one-live-run rule, and the one that is
    going already reads what the registry says now."""

    queued: list[QueuedReparse]
    already_going: list[SourceRef]


class RunRead(BaseModel):
    """One run, named: which channel, of which shop, collecting what."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    source: SourceRef | None = None
    shop: Named | None = None
    category: Named | None = None
    kind: Kind
    status: Status
    started_at: datetime
    finished_at: datetime | None
    duration_seconds: float | None = Field(
        default=None, description="From start to finish; null while it is live"
    )
    items_seen: int
    items_ingested: int
    items_failed: int
    coverage: dict[str, float] = Field(
        description="Share of handed-over listings carrying each field: {field: 0..1}"
    )
    contract: "RunContract"
    error: str | None
    progress: "RunProgressRead"


FAILURE_SAMPLE = 200


class ItemFailure(BaseModel):
    """One product that did not make it into the run, and where it broke.

    `fetch`: its page could not be read. `parse`: the page was read and the channel's parser
    raised on it — the bytes are in the snapshot store's `failed/` area, which is what makes
    it a five-minute fix. `ingest`: parsed, and refused by the service when handed over.
    """

    model_config = ConfigDict(extra="forbid")

    stage: Literal["fetch", "parse", "ingest"]
    external_id: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=1000)
    error: str = Field(max_length=500)


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
    # A sample of what did not make it, each with its reason. Bounded: a run where every
    # product failed says so with its count, and two hundred reasons tell the story.
    failures: list["ItemFailure"] = Field(default_factory=list, max_length=FAILURE_SAMPLE)


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
    # The addresses of the channel's proxy, whole, credentials and all: the worker is what
    # connects. Empty goes direct — no proxy chosen, or the one chosen switched off.
    proxies: list[str] = Field(default_factory=list)


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
    # For each running run, the listings of its channel seen since it started. A worker
    # hands over a slice at a time, so this grows while the run works.
    progress: dict[int, int] = Field(
        description="Running run id → listings of its channel seen since it started"
    )
    due: list[Due]
    channels: list[ChannelSchedule]


class RunProgress(BaseModel):
    """What a worker has done so far. Counts only; each report replaces the last one's."""

    model_config = ConfigDict(extra="forbid")

    phase: str = Field(max_length=20)
    discovered: int | None = Field(default=None, ge=0)
    read: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    handed_over: int = Field(default=0, ge=0)


class RunContract(BaseModel):
    """The contract's verdict and every check behind it. `not_evaluated` for a run that
    broke, or has not finished: judging the counts of a crash is judging nothing."""

    verdict: str | None = None
    checks: list[Check] = Field(default_factory=list)


class SettledCounts(BaseModel):
    renamed: int = 0
    matched: int = 0
    promoted: int = 0
    matched_after: int = 0
    # The visible families of the channel's category before settling and after. More after
    # a reparse is the alarm: rereading what was placed should fold families, not split them.
    families_before: int | None = None
    families_after: int | None = None


class RunProgressRead(BaseModel):
    """What a run has done so far: the worker's counts while it reads, then what settling
    it placed. `phase` walks `reading` → `settling` → `settled` (or `unsettled`, with the
    reason); a quick pass ends at `done`. A reparse finishing while others wait ends at
    `settle_deferred`: the last one of them settles for all."""

    phase: str | None = None
    discovered: int | None = None
    read: int | None = None
    failed: int | None = None
    handed_over: int | None = None
    settled: SettledCounts | None = None
    settle_error: str | None = None


class RunFailures(BaseModel):
    """The sample a run kept of what did not make it, beside how many did not."""

    run_id: int
    items_failed: int
    sampled: int
    items: list[ItemFailure]


RunRead.model_rebuild()
RunResult.model_rebuild()
