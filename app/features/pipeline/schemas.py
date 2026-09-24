"""The collection-to-catalogue pipeline as nodes and the edges between them."""

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
