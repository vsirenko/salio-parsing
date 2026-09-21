"""Matching schemas: what was decided, and what could not be."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Method(StrEnum):
    """Which rung of the ladder fired.

    Kept because trust in them differs wildly: a barcode is proof, a model string that
    happened to agree is a guess that landed.
    """

    GTIN = "gtin"
    BRAND_MPN = "brand_mpn"
    BRAND_MODEL = "brand_model"
    # Needs an offer's attributes resolved to the canonical registry, which nothing does
    # yet. Declared so the ladder is visible in full.
    IDENTITY_KEY = "identity_key"
    JUDGE = "judge"
    HUMAN = "human"


class DecidedBy(StrEnum):
    RULE = "rule"
    JUDGE = "judge"
    HUMAN = "human"


class Reason(StrEnum):
    """Why a listing could not be placed.

    Six different problems that route to six different kinds of work. One
    undifferentiated pile is a pile nobody sorts.
    """

    # The brand string resolved to nothing at all. There is no drawer to look in and no
    # candidate to offer, so finishing this needs a search: someone reads the raw string
    # and decides which brand it is, or that it is a new one.
    BRAND_UNKNOWN = "brand_unknown"
    # The brand string resolved to several brands. Kept apart from the above because the
    # candidates exist and are on the row — this is a choice, and a choice can be made
    # without going looking.
    BRAND_AMBIGUOUS = "brand_ambiguous"
    # No barcode, no part number, no model, no brand. Nothing to match on at all.
    NO_SIGNALS = "no_signals"
    # Signals were there and the catalogue has no such thing. Usually: create the variant.
    SIGNALS_UNMATCHED = "signals_unmatched"
    # Several plausible candidates. A human or a judge picks.
    AMBIGUOUS = "ambiguous"
    # One candidate, not strong enough. No fuzzy rung produces this yet.
    LOW_CONFIDENCE = "low_confidence"


class OfferMatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    offer_id: int
    variant_id: int
    method: Method
    confidence: Decimal
    evidence: dict
    decided_at: datetime
    decided_by: DecidedBy
    superseded_at: datetime | None


class MatchQueueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    offer_id: int
    reason: Reason
    candidates: list
    attempts: int
    last_attempt_at: datetime
    snoozed_until: datetime | None


class ManualMatch(BaseModel):
    """A human placing a listing themselves."""

    model_config = ConfigDict(extra="forbid")

    variant_id: int
    note: str | None = Field(default=None, max_length=500)


class MatchOutcome(BaseModel):
    """What running the matcher over one listing did."""

    offer_id: int
    matched: bool
    method: Method | None
    variant_id: int | None
    reason: Reason | None
    candidates: list


class RunReport(BaseModel):
    attempted: int
    matched: int
    queued: int


class QueueSummary(BaseModel):
    """The breakdown that answers what to build next.

    If most listings sit in `signals_unmatched`, the work is creating variants. In
    `brand_unknown`, it is reading raw strings and naming the brand behind them. In
    `brand_ambiguous` or `ambiguous`, the candidates are already there and the work is
    choosing — the two buckets a judge can help with, and if both are nearly empty, a judge
    is not what this needs. In `no_signals`, it is pulling identity out of titles.
    """

    total: int
    by_reason: dict[str, int]
    matched_offers: int
    offers: int
    matched_share: float
