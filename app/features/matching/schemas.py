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

    Seven different problems that route to seven different kinds of work. One
    undifferentiated pile is a pile nobody sorts — and a pile that says `ambiguous` when
    nothing can settle it is worse than undifferentiated, because it sends somebody to
    choose with nothing to choose from.
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
    # Several candidates that differ in an axis this shop never published. Kept apart from
    # `ambiguous` because that one promises a choice somebody can make, and here nobody can:
    # not a person, not the judge. m79's German feed states the model, the memory, the
    # screen and the refresh rate and never the colour, and the catalogue holds that phone
    # in three of them. 52 of 58 `ambiguous` rows were this, and the judge was being asked
    # about every one of them — `variant_choice` refused 30 of 30 and was right each time.
    AXIS_UNPUBLISHED = "axis_unpublished"
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


class MergeReport(BaseModel):
    """What a pass of merges did.

    A barcode is the strongest thing this system has, so two catalogue entries both holding
    listings that carry one and the same barcode are not two products. `refused` is the
    interesting number: a pair the barcode named and something else contradicted.
    """

    found: int
    merged: int
    refused: int
    # Why a pair was left alone, counted.
    reasons: dict[str, int] = Field(default_factory=dict)
    # The pairs that were folded, newest first, as `from -> into`.
    pairs: list[str] = Field(default_factory=list)


class RenameReport(BaseModel):
    """What a pass of rebuilds did.

    A catalogue entry made from one listing is named after that listing's reading. When the
    reading improves — a rule fixed, a word entered in the registry — the entry keeps the
    old name and nothing goes back for it. `merged` is the good outcome: renamed, the entry
    turned out to be one that already existed.
    """

    found: int
    renamed: int
    merged: int
    refused: int
    reasons: dict[str, int] = Field(default_factory=dict)


class PromotionReport(BaseModel):
    """What a pass of promotions did.

    `matched` is the interesting number: a listing that turned out to match a variant made
    moments earlier, from another shop's listing of the same product. It is the whole point
    of the exercise, and it is why a sweep tries to match before it promotes.
    """

    considered: int
    promoted: int
    matched: int
    skipped: int
    # Why the rest were not promoted, counted. A sweep that reports "48 skipped" and no
    # reason is a sweep nobody can act on.
    reasons: dict[str, int]


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
