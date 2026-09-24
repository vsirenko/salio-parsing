"""Judge schemas: what was asked, what came back, and what code may do with it."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict, Field


class BrandRequest(NamedTuple):
    """One listing to decide a brand for.

    `key` is whatever the caller wants back on the answer — an offer id, in practice. The
    judge does not look at it, which is what keeps this feature from knowing about offers.
    """

    key: int
    title: str | None
    brand_raw: str | None
    model_raw: str | None
    brand_ids: list[int]


class BrandVerdict(NamedTuple):
    """An answer, and whether policy allows acting on it.

    `brand_id` is None both when the model answered "none of these" and when it answered
    something without enough certainty. Those are different facts and both are kept, so a
    queue row can say which happened; but neither one places a listing.
    """

    brand_id: int | None
    choice: str
    confidence: Decimal
    accepted: bool
    # Answered "neither of these", as opposed to answered weakly. Named here so no caller
    # has to know which option key stands for it.
    no_match: bool


class VariantRequest(NamedTuple):
    """One listing to choose a catalogue entry for.

    The brand is named separately from the title because a marketing colour belongs to a
    maker: `Canyon` is pink on a Google and orange on an Oppo, both proved by two shops.
    """

    key: int
    title: str | None
    brand: str | None
    model: str | None
    variant_ids: list[int]


class VariantVerdict(NamedTuple):
    """An answer about which entry a listing is, and whether policy allows acting on it."""

    variant_id: int | None
    choice: str
    confidence: Decimal
    accepted: bool
    no_match: bool


class ColourRequest(NamedTuple):
    """One listing to decide a colour for.

    The title rather than a word cut out of it: only a shop's own ruleset knows where that
    shop puts its colour, and most of them keep it in the title rather than in a field.
    """

    key: int
    title: str | None
    brand: str | None
    model: str | None


class ColourVerdict(NamedTuple):
    """A plain colour, and whether policy allows acting on it."""

    canonical: str | None
    choice: str
    confidence: Decimal
    accepted: bool
    no_match: bool


class MatchCheckRequest(NamedTuple):
    """One match a rule made, to be checked against the listing's own title."""

    key: int
    title: str
    brand: str
    entry_model: str


class MatchCheckVerdict(NamedTuple):
    """What the judge thinks of a match, and whether that is a doubt worth listing.

    `same` is the probability the listing names the entry's own model — the number the
    threshold is on. Not `confidence`, which says how concentrated the answer was: a
    listing the model is sure is a sibling has high confidence and a `same` near nothing.
    """

    choice: str
    confidence: Decimal
    same: Decimal
    doubted: bool


VERDICT_SORT = ("id", "created_at", "confidence", "tokens")


class Kind(StrEnum):
    BRAND_CHOICE = "brand_choice"
    VARIANT_CHOICE = "variant_choice"
    COLOUR_CHOICE = "colour_choice"
    MODEL_MATCH = "model_match"


class Outcome(StrEnum):
    """What policy made of an answer, read off the answer and the thresholds.

    `accepted`: confident enough to act on. `below_threshold`: recorded, not acted on.
    `brand_unknown`: a brand question answered "none of these", which files the listing as
    a brand nobody has; `no_match`: the same answer to the other questions. For a model
    check, `doubt` (listed for a person) or `confirmed`. Whether a listing was then placed
    is on each of `listings`, because it is a fact about the listing now, not the answer.
    """

    ACCEPTED = "accepted"
    BELOW_THRESHOLD = "below_threshold"
    BRAND_UNKNOWN = "brand_unknown"
    NO_MATCH = "no_match"
    DOUBT = "doubt"
    CONFIRMED = "confirmed"


class VerdictOption(BaseModel):
    """One option the judge was offered. `label` is what a person reads — the brand's
    name, the entry's title, the colour — and `key` the slug it was sent as.
    `description` is what the model was told about it; null on answers bought before it
    was kept."""

    key: str
    label: str
    description: str | None


class VerdictAnswer(BaseModel):
    choice: str
    confidence: Decimal
    probabilities: dict[str, float]


class Named(BaseModel):
    id: int
    name: str


class VerdictListing(BaseModel):
    """A listing the question was about, as it stands now. One question can be about
    several: two shops wrote the same title, and it was asked once."""

    offer_id: int
    title: str | None
    shop: Named
    state: str = Field(description="placed, queued or unplaced")
    variant_id: int | None
    method: str | None
    decided_by: str | None


class VerdictReview(BaseModel):
    correct: bool
    note: str | None
    reviewed_by: str | None
    reviewed_at: datetime


class VerdictRead(BaseModel):
    id: int
    kind: Kind
    question_hash: str
    state: dict
    options: list[VerdictOption]
    answer: VerdictAnswer
    choice: str
    choice_label: str
    confidence: Decimal
    model: str
    input_tokens: int
    output_tokens: int
    created_at: datetime
    forgotten_at: datetime | None
    outcome: Outcome
    listings: list[VerdictListing]
    review: VerdictReview | None


class ReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correct: bool
    note: str | None = Field(default=None, max_length=500)


class CalibrationBucket(BaseModel):
    low: Decimal
    high: Decimal
    answers: int
    reviewed: int
    correct: int
    incorrect: int


class Calibration(BaseModel):
    """Answers bucketed by the number their threshold is on, with what people said.

    For a choice that number is `confidence`; for a model check it is the probability of
    `same`, because that is what `JUDGE_DOUBT_BELOW` compares — a check that is sure the
    listing is a sibling has high confidence and a `same` near nothing.
    """

    kind: Kind | None
    score: str
    threshold: float
    buckets: list[CalibrationBucket]


class UsageDay(BaseModel):
    day: date
    kind: Kind
    asked: int
    cached: int
    input_tokens: int
    output_tokens: int


class JudgeConfig(BaseModel):
    """Whether the judge can be asked at all, and the numbers its answers are read by."""

    enabled: bool
    model: str
    min_confidence: float
    doubt_below: float
    concurrency: int
    timeout_seconds: float


class PendingKind(BaseModel):
    """What a pass of one kind would pay for if started now.

    `eligible` is every listing it would consider with no limit; `to_ask` the distinct
    questions among them the store has no answer for — two shops writing one title are one
    question. The tokens are that times this kind's average so far, null before any answer
    of the kind was bought.
    """

    kind: Kind
    eligible: int
    to_ask: int
    estimated_input_tokens: int | None
    estimated_output_tokens: int | None


class JudgeReport(BaseModel):
    """What a pass over the queue did, in the terms that decide whether to run it again.

    `asked` is what was paid for and `cached` is what was not, so the two together say
    whether the store is earning its keep.
    """

    considered: int
    asked: int
    cached: int
    accepted: int
    unconfident: int
    no_match: int
    failed: int
    placed: int
    # Matches the answer casts doubt on. Only the match check fills it; for the questions
    # that choose, a doubt is not a thing they produce.
    doubted: int = 0
    input_tokens: int
    output_tokens: int
    # The first failure, named. A pass that reports twenty failures and no reason is a
    # pass nobody can fix.
    error: str | None = None


class JudgeWindow(BaseModel):
    """What the judge cost over one stretch of time.

    `asked` and the tokens are the answers bought — one stored verdict each, so they are
    exact. `cached` is how many questions were answered from the store instead, summed from
    the passes' own reports in the audit trail: a cache hit writes no verdict, and the
    trail is the one place it is recorded. No money: the price per token is the provider's
    and changes, and a figure computed from a stale one would be believed.
    """

    since: datetime | None
    passes: int
    asked: int
    cached: int
    input_tokens: int
    output_tokens: int
    by_kind: dict[str, int]


class JudgeSummary(BaseModel):
    day: JudgeWindow
    week: JudgeWindow
    all_time: JudgeWindow
