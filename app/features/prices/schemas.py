"""Price and availability history schemas."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


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
