"""The collection-to-catalogue pipeline as nodes and the edges between them."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class Stage(BaseModel):
    """One node: how many things reached it, and what they are made of."""

    key: str
    label: str
    count: int
    parts: dict[str, int]
    # Only on `read`: for each axis the categories require, how many listings read without
    # it. Beside `parts` rather than in it, so `parts` stays one number per key.
    missing_axes: dict[str, int] = Field(default_factory=dict)


class Edge(BaseModel):
    """What passed from one node to the next. The difference to `source`'s count is what
    stopped there."""

    source: str
    target: str
    count: int


class SourceFlow(BaseModel):
    """One channel's own pass through the same nodes."""

    source_id: int
    source: str
    shop_id: int
    shop: str
    category: str | None
    category_id: int | None
    category_slug: str | None
    category_name: str | None
    # The last full pass, whose status `last_run_status` is — to open it.
    last_run_id: int | None
    scheduled: bool
    last_run_status: str | None
    collected: int
    listed: int
    delisted: int
    read: int
    with_model: int
    with_gtin: int
    all_axes: int
    placed: int
    queued: int
    missing_axes: dict[str, int] = Field(default_factory=dict)


class Pipeline(BaseModel):
    """The pipeline for one category, one channel or everything, with the channels under it."""

    category: str | None
    source: str | None
    stages: list[Stage]
    edges: list[Edge]
    sources: list[SourceFlow]


class RunFlow(BaseModel):
    """One run through the same nodes, filling in while it runs.

    The first half is what the worker reported (`progress`): how many product pages it found,
    read and handed over. The second half is counted from the tables: what became of the
    listings this run saw, and what settling it placed. Both are there as the run goes, so a
    page polling this watches the nodes fill in order.
    """

    run_id: int
    source: str
    shop: str
    category: str | None
    kind: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    error: str | None
    phase: str
    progress: dict
    stages: list[Stage]
    edges: list[Edge]


class PipelineDay(BaseModel):
    """The pipeline's key numbers as they stood on one day. Missing days were not kept —
    the scheduler was not running — and cannot be recomputed."""

    day: date
    scope: str
    listed: int
    delisted: int
    read: int
    with_model: int
    with_gtin: int
    all_axes: int
    missing_axes: dict[str, int]
    placed: int
    placed_by_method: dict[str, int]
    queued: int
    queued_by_reason: dict[str, int]
    collected: int
    variants: int
    families: int
