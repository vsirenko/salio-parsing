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
    attributes: dict[str, Any]
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
