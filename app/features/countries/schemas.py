"""Country schemas.

A country is not a market. A shop in Germany may deliver to Riga while we run no German
storefront at all — Germany still needs a row here, for its VAT rate and for the shop to
point at. The storefronts we actually run get their own entity.
"""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CountryBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    currency_code: str = Field(min_length=3, max_length=3)
    # A fraction, not a percentage: 0.21 rather than 21. It is multiplied, never divided
    # by a hundred somewhere further down.
    vat_standard_rate: Decimal | None = Field(default=None, ge=0, le=1, decimal_places=4)
    is_eu: bool = False


class CountryCreate(CountryBase):
    """Adding a country we have started to see shops from.

    The seed carries only the markets we serve; the rest arrive this way rather than
    through a migration, for the same reason a new market does — it is data, not a
    release.
    """

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=2, max_length=2)

    @field_validator("code", "currency_code")
    @classmethod
    def _uppercase(cls, value: str) -> str:
        return value.upper()


class CountryRead(CountryBase):
    model_config = ConfigDict(from_attributes=True)

    code: str


class CountryUpdate(BaseModel):
    """Every field optional; only what is sent is applied.

    The code is the identity and is not editable — a country that changes its ISO code is
    a new row, not an edit.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    vat_standard_rate: Decimal | None = Field(default=None, ge=0, le=1, decimal_places=4)
    is_eu: bool | None = None

    @field_validator("currency_code")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()
