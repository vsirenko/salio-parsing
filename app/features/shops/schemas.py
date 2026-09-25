"""Shop schemas.

A shop is who the buyer deals with, a source is how we read its offers, and a seller is who
is actually selling inside it. Three things, not one — keeping them apart is what stops a
shop with a feed and a scraper turning into two shops on a card.
"""

import re
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, field_validator

SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _validate_slug(value: str) -> str:
    if not SLUG.match(value):
        raise ValueError("must be lowercase letters, digits and single hyphens")
    return value


def _validate_cron(value: str | None) -> str | None:
    """Refused here rather than at tick time.

    A malformed expression that is only noticed by the scheduler stops that channel
    silently: nothing fails, it simply never becomes due, and the first symptom is stale
    prices nobody can explain.
    """
    if value is None:
        return None
    if not croniter.is_valid(value):
        raise ValueError(f"'{value}' is not a cron expression")
    return value


class Access(StrEnum):
    """How many requests a product costs, which is what decides the schedule."""

    # One request, or a few pages, returns everything. A feed. There is no cheap pass,
    # because the expensive one is already the whole thing.
    WHOLESALE = "wholesale"
    # A listing, then a request per product.
    RETAIL = "retail"


class Decode(StrEnum):
    """How a response turns into fields.

    The smallest part, and the one that changes without affecting anything else. Most
    shops already publish machine-readable product data inside the page — for search
    engines, or for their own front end — so reading markup is the fallback for the rest.
    """

    JSON_LD = "json_ld"
    EMBEDDED_STATE = "embedded_state"
    GRAPHQL = "graphql"
    PRIVATE_API = "private_api"
    XML = "xml"
    MARKUP = "markup"


class Fact(StrEnum):
    """What a pass can bring back.

    `catalogue` is everything matching stands on: barcodes, part numbers, model strings,
    attributes. The other two are observations about one listing at one moment.
    """

    CATALOGUE = "catalogue"
    PRICE = "price"
    AVAILABILITY = "availability"


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
    shops_count: int = 0


class ShopGroupUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("slug")
    @classmethod
    def _check(cls, value: str | None) -> str | None:
        return None if value is None else _validate_slug(value)


class GroupRef(BaseModel):
    id: int
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
    logo_url: str | None = Field(default=None, max_length=1000)
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
    logo_url: str | None = Field(default=None, max_length=1000)
    rating: Decimal | None = Field(default=None, ge=0, le=5)

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, value: str | None) -> str | None:
        return None if value is None else _validate_slug(value)

    @field_validator("country_code")
    @classmethod
    def _upper(cls, value: str | None) -> str | None:
        return None if value is None else value.upper()


# What a list of shops may be sorted by, `?sort=`.
SHOP_SORT = (
    "id",
    "name",
    "slug",
    "created_at",
    "sources_count",
    "offers_count",
    "products_count",
    "last_full_ok_at",
)


class CollectionHealth(BaseModel):
    """Whether a shop's collection is working, from its enabled channels' full passes.

    `failing` when an enabled channel's newest full pass did not end ok — failed, rejected by
    its contract, or interrupted; `never` when no enabled channel has finished one ok yet;
    `ok` otherwise. A channel that is disabled says nothing about the shop's health.
    """

    status: str = Field(description="`ok`, `failing` or `never`")
    last_full_ok_at: datetime | None = Field(
        description="When the newest full pass that ended ok, on any channel, finished"
    )
    enabled_sources: int
    failing_sources: int = Field(
        description="Enabled channels whose newest full pass did not end ok"
    )


class ShopRead(BaseModel):
    """A shop, with where it is shown, what it holds and whether its collection works."""

    id: int
    slug: str
    name: str
    country_code: str
    group: GroupRef | None
    website: str | None
    logo_url: str | None
    is_marketplace: bool
    rating: Decimal | None
    created_at: datetime
    markets: list[str] = Field(description="The markets it is shown in")
    hidden_markets: list[str] = Field(
        default_factory=list, description="The markets it is attached to and not shown in"
    )
    sources_count: int
    sellers_count: int
    offers_count: int = Field(description="Its listings on sale now, of any condition")
    products_count: int = Field(description="Families it sells new today")
    health: CollectionHealth


class MarketState(StrEnum):
    """Where a shop stands in one market, for `?market_code=`."""

    SHOWN = "shown"
    HIDDEN = "hidden"
    # Either of the two: every shop the market card lists, with a switch on each.
    ATTACHED = "attached"


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
    access: Access
    decode: Decode
    delivers_full: list[Fact] = Field(min_length=1)
    delivers_quick: list[Fact] = Field(default_factory=list)
    category_id: int | None = None
    trust: Trust = Trust.MEDIUM
    base_url: str | None = Field(default=None, max_length=1000)
    is_enabled: bool = False
    cron_full: str | None = Field(default=None, max_length=64)
    cron_quick: str | None = Field(default=None, max_length=64)
    min_items: int | None = Field(default=None, gt=0)
    max_drop_pct: int = Field(default=30, ge=0, le=100)
    min_price_coverage: Decimal = Field(default=Decimal("0.98"), ge=0, le=1)
    # The proxy its runs go out through (`/api/admin/proxies`); none goes direct.
    proxy_id: int | None = None

    @field_validator("slug")
    @classmethod
    def _check(cls, value: str) -> str:
        return _validate_slug(value)

    @field_validator("cron_full", "cron_quick")
    @classmethod
    def _check_cron(cls, value: str | None) -> str | None:
        return _validate_cron(value)


class SourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access: Access | None = None
    decode: Decode | None = None
    delivers_full: list[Fact] | None = Field(default=None, min_length=1)
    delivers_quick: list[Fact] | None = None
    category_id: int | None = None
    trust: Trust | None = None
    base_url: str | None = Field(default=None, max_length=1000)
    is_enabled: bool | None = None
    cron_full: str | None = Field(default=None, max_length=64)
    cron_quick: str | None = Field(default=None, max_length=64)
    min_items: int | None = Field(default=None, gt=0)
    max_drop_pct: int | None = Field(default=None, ge=0, le=100)
    min_price_coverage: Decimal | None = Field(default=None, ge=0, le=1)
    # Null takes the proxy away and the channel goes direct.
    proxy_id: int | None = None

    @field_validator("cron_full", "cron_quick")
    @classmethod
    def _check_cron(cls, value: str | None) -> str | None:
        return _validate_cron(value)


class RunBrief(BaseModel):
    """A channel's newest run, as a list row shows it."""

    id: int
    kind: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    items_seen: int
    error: str | None


class SourceRead(BaseModel):
    """A channel, with its newest run, its next slots and what it has on sale now."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    shop_id: int
    slug: str
    access: Access
    decode: Decode
    delivers_full: list[Fact]
    delivers_quick: list[Fact]
    category_id: int | None
    trust: Trust
    base_url: str | None
    is_enabled: bool
    cron_full: str | None
    cron_quick: str | None
    min_items: int | None
    max_drop_pct: int
    min_price_coverage: Decimal
    proxy_id: int | None = Field(default=None, description="The proxy its runs go out through")
    last_run: RunBrief | None = None
    last_full_ok_at: datetime | None = Field(
        default=None, description="When its newest full pass that ended ok finished"
    )
    next_full_at: datetime | None = Field(
        default=None, description="Its next scheduled full pass; none while disabled"
    )
    next_quick_at: datetime | None = None
    offers_count: int = Field(default=0, description="Its listings on sale now")


# --- who is selling ---


class SellerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)


class SellerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)


class SellerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shop_id: int
    external_id: str
    name: str
    offers_count: int = Field(default=0, description="Its listings on sale now")
