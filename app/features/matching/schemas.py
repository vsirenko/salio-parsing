"""Matching schemas: what was decided, and what could not be."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


QUEUE_SORT = ("offer_id", "attempts", "last_attempt_at", "siblings", "title", "price")
DOUBT_SORT = ("offer_id", "same", "price")


class NamedRef(BaseModel):
    id: int
    name: str


class AxisCompare(BaseModel):
    """One identity axis, as the listing and the candidate each hold it.

    `agrees` is null when one side has nothing on it: a silence, which the ladder treats
    differently from a disagreement — and so should whoever is choosing.
    """

    key: str
    listing: str | None
    entry: str | None
    agrees: bool | None


class Candidate(BaseModel):
    """A near miss the matcher found while failing, and why it was considered.

    A variant for the rungs that search entries; a brand for `brand_ambiguous`, whose
    question is which maker a string means. `why` is the signal that found it — `gtin`,
    `mpn`, `model`, `brand_alias` — and `axes` how it compares with the listing now, read
    against the catalogue as it is rather than as it was when the row was written. There is
    no score: the ladder does not rank, it agrees or refuses, and a number here would be one
    invented for the page.
    """

    why: str
    variant_id: int | None = None
    brand_id: int | None = None
    variant_title: str | None = None
    model: str | None = None
    brand: NamedRef | None = None
    offers_count: int | None = Field(
        default=None, description="Listings placed on this entry — how settled it is"
    )
    axes: list[AxisCompare] = Field(default_factory=list)


class OfferBrief(BaseModel):
    """The listing a queue row or a doubt is about, enough to decide from the row."""

    id: int
    title: str | None
    shop: NamedRef
    external_id: str
    url: str | None
    brand_raw: str | None
    gtin: str | None
    price: Decimal | None
    currency_code: str | None
    condition: str
    category: NamedRef | None


class CreatedVariant(BaseModel):
    """The entry a promotion makes. `id` is null on a dry run, which made nothing."""

    id: int | None
    title: str
    model: str
    brand: str
    offer_id: int


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


class MatchDoubtRead(BaseModel):
    """A match a rule made that the judge doubts, with what it was shown and what it said.

    Read-only on purpose. A doubt is a question for a person — unlink, split, merge or
    leave — and never a reason for the matcher to move a listing by itself.
    """

    offer_id: int
    variant_id: int
    method: Method
    listing_title: str
    brand: str
    entry_model: str
    variant_title: str
    offer: OfferBrief
    # The judge's answer, `same` being the probability the listing names the entry's own
    # model — what the review threshold is on.
    choice: str
    same: Decimal
    confidence: Decimal
    verdict_id: int


class MatchQueueRead(BaseModel):
    """A listing the matcher could not place, with the listing itself and what it found.

    `brand` and `model_key` are what it looked for; `siblings` counts the queued listings
    looking for the same brand and model — what one new entry would place.
    """

    offer_id: int
    reason: Reason
    candidates: list[Candidate]
    attempts: int
    last_attempt_at: datetime
    snoozed_until: datetime | None
    offer: OfferBrief
    brand: NamedRef | None
    model_key: str | None
    siblings: int


class Snooze(BaseModel):
    model_config = ConfigDict(extra="forbid")

    until: datetime

    @field_validator("until")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("give a time zone: a bare time is a different moment per reader")
        return value


class DoubtKept(BaseModel):
    """A doubted match a person looked at and left where it was."""

    offer_id: int
    variant_id: int
    method: Method
    decided_by: DecidedBy


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
    candidates: list[Candidate]
    # A promotion's entry. On a dry run the listing is placed on it as it would be and
    # none of it is kept, so `variant_id` names nothing afterwards either.
    created: CreatedVariant | None = None
    dry_run: bool = False


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
    # Every pair the barcode named, folded or refused, in the order they were tried.
    pairs: list["MergePair"] = Field(default_factory=list)
    dry_run: bool = False


class EntrySnapshot(BaseModel):
    """A catalogue entry as it stood before the pair was tried. Null fields mean it was
    already gone — folded into another by an earlier pair of the same pass."""

    id: int
    title: str | None
    model: str | None
    brand: str | None
    offers_count: int


class MergePair(BaseModel):
    """Two entries one barcode named, and what became of them.

    `from` is folded in and disappears, `into` survives. A refused pair is the one worth
    reading: one barcode on two brands or two categories is more often an error in a shop's
    data than two products.
    """

    model_config = ConfigDict(populate_by_name=True)

    gtin: str
    from_: EntrySnapshot = Field(alias="from")
    into: EntrySnapshot
    outcome: Literal["merged", "refused"]
    reason: str | None = None
    detail: str | None = Field(default=None, description="What the refusal said")


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
    # Moved into the family its name says: a renamed entry, or one renamed before the
    # pass learned to move it, still filed under the product the old name had made.
    rehomed: int = 0
    # Families renamed to the case every entry in them writes their name in.
    recased: int = 0
    # Families left with nothing in them, hidden rather than deleted.
    hidden: int = 0
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
    # The entries made, oldest first. On a dry run, the ones that would be.
    created: list[CreatedVariant] = Field(default_factory=list)
    dry_run: bool = False


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
