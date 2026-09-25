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


# What a list of listings may be sorted by, `?sort=`.
OFFER_SORT = ("id", "price", "last_seen_at", "first_seen_at", "shop", "title")


class MatchState(StrEnum):
    """Where the matcher left a listing. `queued` holds the ambiguous ones too — which kind
    of stuck it is, is the queue's `reason`."""

    PLACED = "placed"
    QUEUED = "queued"
    UNPLACED = "unplaced"


class MatchMethod(StrEnum):
    GTIN = "gtin"
    BRAND_MPN = "brand_mpn"
    BRAND_MODEL = "brand_model"
    IDENTITY_KEY = "identity_key"
    JUDGE = "judge"
    HUMAN = "human"


class QueueReason(StrEnum):
    BRAND_UNKNOWN = "brand_unknown"
    BRAND_AMBIGUOUS = "brand_ambiguous"
    NO_SIGNALS = "no_signals"
    SIGNALS_UNMATCHED = "signals_unmatched"
    AMBIGUOUS = "ambiguous"
    LOW_CONFIDENCE = "low_confidence"
    AXIS_UNPUBLISHED = "axis_unpublished"


class ShopRef(BaseModel):
    id: int
    name: str


class NamedRef(BaseModel):
    id: int
    name: str


class SellerRef(BaseModel):
    """Who sells it within the shop: the shop itself, or a trader on a marketplace."""

    id: int
    name: str


class PlacedOn(BaseModel):
    """The catalogue entry a listing is placed on, and by what signal."""

    variant_id: int
    variant_title: str
    method: str


class OfferRead(BaseModel):
    """One listing, with the shop that has it and where the catalogue placed it.

    `listed` is whether the shop still has it: seen by its channel's newest full pass that
    ended ok. A listing the shop took down keeps its history and its last price, which is
    no longer a price anybody can pay.
    """

    id: int
    shop: ShopRef
    seller: SellerRef
    title: str | None = Field(description="As the shop wrote it, from its newest full pass")
    brand_raw: str | None = Field(description="The brand as the shop wrote it")
    gtin: str | None = Field(description="The barcode the reading accepted")
    brand: NamedRef | None = Field(description="The placed product's brand; null unplaced")
    category: NamedRef | None = Field(
        description="The placed product's category, else what the channel collects"
    )
    match_state: MatchState
    queue_reason: QueueReason | None
    placed_on: PlacedOn | None
    listed: bool
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


# --- the path of one listing, for a person to follow ---


class TraceStep(BaseModel):
    """One rule as it ran on this listing, and exactly what it changed."""

    rule: str
    layer: str
    # The reader makes two rounds: the second re-runs the brand's layers and below once the
    # brand is known.
    round: int
    why: str
    changed: dict[str, list[Any]]


class TraceObservation(BaseModel):
    """What the shop served, as the channel parsed it — the newest pass that carried it."""

    raw_offer_id: int
    run_id: int | None
    run_kind: str | None
    fetched_at: datetime
    payload: dict[str, Any]


class TraceReading(BaseModel):
    ruleset_version: str
    fields: dict[str, Any]


class TraceMatch(BaseModel):
    variant_id: int
    method: str
    confidence: Decimal
    decided_by: str
    decided_at: datetime
    superseded_at: datetime | None
    evidence: dict[str, Any]


class TraceCandidate(BaseModel):
    """A near miss as the queue row stored it, named. Compared axis by axis with the
    listing in `GET /api/admin/match-queue/{offer_id}`, which is where the choosing is."""

    why: str
    variant_id: int | None = None
    brand_id: int | None = None
    variant_title: str | None = None
    model: str | None = None
    brand: NamedRef | None = None


class TraceQueue(BaseModel):
    reason: str
    candidates: list[TraceCandidate]
    attempts: int
    last_attempt_at: datetime


class TraceEntry(BaseModel):
    """The catalogue entry the listing is on, and who else is."""

    variant_id: int
    model: str
    title: str
    identity_key: str | None
    axes: dict[str, str]
    product_id: int | None
    product_title: str | None
    listings_by_shop: dict[str, int]


class OfferTrace(BaseModel):
    """One listing from the shop's bytes to the catalogue, step by step.

    `now` is the reading recomputed with today's rules and words, with `steps` saying how it
    was reached; `stored` is what the database holds. They differ when a rule or the registry
    changed since the listing was last read, which is what `stale` says.
    """

    offer_id: int
    shop: str
    source: str | None
    category: str | None
    url: str | None
    price: Decimal | None
    currency_code: str | None
    availability: str
    observation: TraceObservation | None
    stored: TraceReading | None
    now: TraceReading | None
    stale: bool
    steps: list[TraceStep]
    match: TraceMatch | None
    history: list[TraceMatch]
    queue: TraceQueue | None
    entry: TraceEntry | None


class UnresolvedReason(StrEnum):
    """Why a listing's colour field left its reading without a colour.

    `unknown`: the registry has no word for what the shop wrote — a row to enter. `pair`: it
    knows each colour and not the combination. `conflict`:
    every field resolves, to different colours, and the reading takes none of them, as it
    should; no alias fixes that. `resolves_now`: the fields agree under the registry as it is
    today and the stored reading is older — a reparse fills it.
    """

    UNKNOWN = "unknown"
    # Two or more colours the registry knows, written as one, whose combination is not a
    # value: `sudraba, zila`. A two-tone value to add, or a word to mark as none — never
    # an alias, which would file the product under one of its colours.
    PAIR = "pair"
    CONFLICT = "conflict"
    RESOLVES_NOW = "resolves_now"


class UnresolvedExample(BaseModel):
    offer_id: int
    title: str | None
    shop: str
    field: str
    written: str


class UnresolvedValue(BaseModel):
    """One thing shops write in a colour field, and why it did not become a colour."""

    value: str = Field(description="Casefolded and trimmed, as it is grouped and marked")
    spellings: list[str] = Field(description="How shops actually wrote it, a few")
    reason: UnresolvedReason
    resolves_to: str | None = Field(description="What it resolves to now, where it does")
    conflicts_with: list[str] = Field(
        default_factory=list, description="The other fields' colours, for a conflict"
    )
    listings: int
    shops: list[str]
    examples: list[UnresolvedExample]
    dismissed: bool


class UnresolvedReport(BaseModel):
    """The listings with a colour field and no colour in their reading, and why.

    Computed from the current readings with the registry as it is now, so it is never stale
    and stores nothing; a listing with no colour field at all is not here — that colour is
    in its title, which is the judge's.
    """

    listings: int
    by_reason: dict[str, int]
    values: list[UnresolvedValue]


class RereadReport(BaseModel):
    """What a re-read of a channel's stored payloads did; `next_after_id` pages on."""

    source_id: int
    read: int
    next_after_id: int | None = None
