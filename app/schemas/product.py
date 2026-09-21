"""Product request/response schemas."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ProductBase(BaseModel):
    name: str = Field(min_length=1, max_length=200, examples=["Espresso machine"])
    description: str | None = Field(default=None, max_length=2000)
    price: Decimal = Field(gt=0, max_digits=12, decimal_places=2, examples=["499.99"])
    currency: str = Field(default="EUR", min_length=3, max_length=3, examples=["EUR"])
    in_stock: bool = True
    tags: list[str] = Field(default_factory=list, max_length=20)

    # Decimal keeps the money math exact; JSON stays a plain number.
    @field_serializer("price", when_used="json")
    def _serialize_price(self, value: Decimal) -> float:
        return float(value)


class ProductCreate(ProductBase):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "name": "Espresso machine",
                "description": "Two-group lever machine",
                "price": 499.99,
                "currency": "EUR",
                "in_stock": True,
                "tags": ["kitchen", "coffee"],
            }
        },
    )


class ProductRead(ProductBase):
    id: int
    created_at: datetime
