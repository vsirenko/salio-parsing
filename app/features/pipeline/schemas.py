"""The collection-to-catalogue pipeline as nodes and the edges between them."""

from datetime import datetime

from pydantic import BaseModel


class Stage(BaseModel):
    """One node: how many things reached it, and what they are made of."""

    key: str
    label: str
    count: int
    parts: dict[str, int]


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
    shop: str
    category: str | None
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
