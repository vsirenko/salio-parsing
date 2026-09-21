"""Price history schemas."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class PriceEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    at: datetime
    offer_id: int
    seller_id: int
    market_code: str
    condition: str
    # A hint for queries, not what the row is about. The row is about the offer.
    variant_id: int | None
    price: Decimal | None
    currency_code: str | None
    availability: str
