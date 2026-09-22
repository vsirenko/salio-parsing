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
    input_tokens: int
    output_tokens: int
    # The first failure, named. A pass that reports twenty failures and no reason is a
    # pass nobody can fix.
    error: str | None = None
