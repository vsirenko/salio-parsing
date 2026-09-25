"""Price and availability history schemas."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class _EventBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    at: datetime
    offer_id: int
    seller_id: int
    market_code: str
    condition: str
    # A hint for queries, not what the row is about. The row is about the listing.
    variant_id: int | None
    # Which channel said so. Two channels of one shop can disagree.
    source_id: int | None


class PriceEventRead(_EventBase):
    price: Decimal | None
    currency_code: str | None


class AvailabilityEventRead(_EventBase):
    availability: str


class DayPrice(BaseModel):
    """One day of a variant's or a family's price across the listings on sale that day."""

    day: date
    min: Decimal
    median: Decimal
    max: Decimal
    listings: int = Field(description="Listings with a price that day")


class ShopPoint(BaseModel):
    day: date
    price: Decimal = Field(description="The shop's lowest price that day")


class ShopSeries(BaseModel):
    shop_id: int
    shop_name: str
    points: list[ShopPoint]


class PriceSeries(BaseModel):
    """What a price chart draws: a band across the market and a line per shop, by day.

    Days are UTC. A day with no listing on sale is left out, so a chart draws a gap there
    rather than a zero.
    """

    variant_id: int | None = None
    product_id: int | None = None
    market_code: str
    condition: str
    currency_code: str | None
    since: date
    until: date
    days: list[DayPrice]
    shops: list[ShopSeries]
