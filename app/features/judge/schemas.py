"""Judge schemas: what was asked, what came back, and what code may do with it."""

from datetime import datetime
from decimal import Decimal
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict


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


class VerdictRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    question_hash: str
    state: dict
    options: list
    answer: dict
    choice: str
    confidence: Decimal
    model: str
    input_tokens: int
    output_tokens: int
    created_at: datetime


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
