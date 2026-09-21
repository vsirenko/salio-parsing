"""Currency schemas. ISO 4217, reference data."""

from pydantic import BaseModel, ConfigDict


class CurrencyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    symbol: str | None = None
    minor_units: int
