"""Offer schemas: the listing, the observation, and our reading of it."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Condition(StrEnum):
    NEW = "new"
    REFURBISHED = "refurbished"
    USED = "used"


class Availability(StrEnum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    PREORDER = "preorder"
    UNKNOWN = "unknown"


class RawOfferIngest(BaseModel):
    """One observation, as a fetcher would submit it.

    The payload is stored verbatim — this is the only place in the system where bytes from
    outside are kept as they arrived, and everything downstream is derived from it.
    """

    model_config = ConfigDict(extra="forbid")

    # Together with the seller this is the listing's identity, which is what lets a feed
    # and a scraper of one shop converge on one offer instead of creating two.
    external_id: str = Field(min_length=1, max_length=200)
    market_code: str = Field(min_length=2, max_length=2)
    payload: dict[str, Any]
    # Only needed when the shop is a marketplace; an ordinary shop has exactly one seller.
    seller_external_id: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=1000)
    condition: Condition = Condition.NEW
    condition_grade: str | None = Field(default=None, max_length=50)


class RawOfferBatch(BaseModel):
    """Many observations of one channel, in one request.

    One at a time, a full pass of a nine-hundred-product shop is nine hundred requests,
    nine hundred transactions and nine hundred audit entries — and that last one is the
    real objection: the trail exists to show what an administrator did, and a crawl would
    bury that under a wall of "an offer arrived".

    Post it gzipped. Product JSON compresses by roughly an order of magnitude, and the
    difference is paid on every pass of every channel.
    """

    model_config = ConfigDict(extra="forbid")

    # On the batch rather than on each item: every observation in one pass comes from one
    # channel showing one market, and repeating it per item invites them to disagree.
    market_code: str = Field(min_length=2, max_length=2)
    offers: list["BatchOffer"] = Field(min_length=1)
    # The run that collected these, when a run did. Absent when a sample is loaded by hand.
    run_id: int | None = None


class BatchOffer(BaseModel):
    """One observation inside a batch. The same thing as a single ingest, less the market."""

    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1, max_length=200)
    payload: dict[str, Any]
    seller_external_id: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=1000)
    condition: Condition = Condition.NEW
    condition_grade: str | None = Field(default=None, max_length=50)


class BatchFailure(BaseModel):
    """One observation that did not go in, and why.

    Named rather than counted: a batch reporting "two failed" is a batch nobody can fix.
    """

    external_id: str
    code: str
    message: str


class BatchResult(BaseModel):
    """What a batch did, in the terms the run's own counters are kept in.

    Partial on purpose. One malformed card in nine hundred should not throw away the pass
    that collected the other eight hundred and ninety-nine — that is exactly the case
    `runs.items_failed` exists to record.
    """

    accepted: int
    failed: int
    # Observations that were genuinely new. The rest hashed to something already on file,
    # so they bumped a timestamp and wrote nothing.
    stored: int
    offers_created: int
    # What was actually read out of this batch, per field, as a fraction of what was
    # accepted. Measured here rather than reported by the worker on purpose: it has to be
    # the same reading the matcher will use, or the number describes the parser's opinion
    # of itself.
    coverage: dict[str, float] = Field(default_factory=dict)
    failures: list[BatchFailure]


class IngestResult(BaseModel):
    """What the observation did.

    `stored` is false when the content hashed to something already on file: an unchanged
    page bumps a timestamp and writes nothing, which is what keeps the raw table
    proportional to how much the world changes rather than how often we look.
    """

    offer_id: int
    raw_offer_id: int
    normalized_offer_id: int | None
    offer_created: bool
    stored: bool
    # Which identity-bearing fields the reading actually found. Not part of the wire
    # contract for a single ingest — it is what a batch sums into its coverage.
    read: list[str] = Field(default_factory=list, exclude=True)


class OfferRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    seller_id: int
    market_code: str
    external_id: str
    url: str | None
    condition: Condition
    condition_grade: str | None
    price: Decimal | None
    currency_code: str | None
    availability: Availability
    first_seen_at: datetime
    last_seen_at: datetime


class RawOfferRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    offer_id: int
    source_id: int
    run_id: int | None
    content_hash: str
    payload: dict[str, Any]
    fetched_at: datetime
    last_seen_at: datetime


class NormalizedOfferRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    raw_offer_id: int
    ruleset_version: str
    title: str | None
    brand_raw: str | None
    brand_id: int | None
    category_raw: str | None
    category_id: int | None
    gtin: str | None
    mpn: str | None
    model: str | None
    attributes: dict
    identity: dict[str, Any]
    price: Decimal | None
    currency_code: str | None
    condition: Condition
    availability: Availability


class Coverage(BaseModel):
    """How far a deterministic matcher could get on what has been read so far.

    The number the whole design is downstream of. Everything after the matcher is shaped by
    whether a barcode is usually there or almost never.
    """

    normalized_offers: int
    with_gtin: int
    with_brand_and_mpn: int
    with_brand_only: int
    with_nothing: int
    gtin_share: float
    deterministic_share: float
