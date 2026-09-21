"""Shop schemas.

A shop is who the buyer deals with, a source is how we read its offers, and a seller is who
is actually selling inside it. Three things, not one — keeping them apart is what stops a
shop with a feed and a scraper turning into two shops on a card.
"""

import re
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _validate_slug(value: str) -> str:
    if not SLUG.match(value):
        raise ValueError("must be lowercase letters, digits and single hyphens")
    return value


class SourceKind(StrEnum):
    FEED = "feed"
    API = "api"
    SCRAPE = "scrape"


class Trust(StrEnum):
    """How much the channel's data is worth, not how good the shop is."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# --- groups ---


class ShopGroupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)

    @field_validator("slug")
    @classmethod
    def _check(cls, value: str) -> str:
        return _validate_slug(value)


class ShopGroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str


# --- shops ---


class ShopCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    # A country, not a market: a German shop delivering to Riga is describable even though
    # we run no German storefront.
    country_code: str = Field(min_length=2, max_length=2)
    shop_group_id: int | None = None
    website: str | None = Field(default=None, max_length=1000)
    is_marketplace: bool = False
    rating: Decimal | None = Field(default=None, ge=0, le=5)

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, value: str) -> str:
        return _validate_slug(value)

    @field_validator("country_code")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()


class ShopUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=64)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    shop_group_id: int | None = None
    website: str | None = Field(default=None, max_length=1000)
    rating: Decimal | None = Field(default=None, ge=0, le=5)

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, value: str | None) -> str | None:
        return None if value is None else _validate_slug(value)

    @field_validator("country_code")
    @classmethod
    def _upper(cls, value: str | None) -> str | None:
        return None if value is None else value.upper()


class ShopRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    country_code: str
    shop_group_id: int | None
    website: str | None
    is_marketplace: bool
    rating: Decimal | None
    created_at: datetime


# --- where its offers are shown ---


class ShopMarketSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # False by default: a shop is attached to a market, checked, and only then shown.
    is_enabled: bool = False


class ShopMarketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    shop_id: int
    market_code: str
    is_enabled: bool


# --- how we read it ---


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=64)
    kind: SourceKind
    trust: Trust = Trust.MEDIUM
    base_url: str | None = Field(default=None, max_length=1000)
    is_enabled: bool = False

    @field_validator("slug")
    @classmethod
    def _check(cls, value: str) -> str:
        return _validate_slug(value)


class SourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: SourceKind | None = None
    trust: Trust | None = None
    base_url: str | None = Field(default=None, max_length=1000)
    is_enabled: bool | None = None


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shop_id: int
    slug: str
    kind: SourceKind
    trust: Trust
    base_url: str | None
    is_enabled: bool


# --- who is selling ---


class SellerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)


class SellerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shop_id: int
    external_id: str
    name: str
