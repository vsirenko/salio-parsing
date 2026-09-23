"""Attribute schemas.

One canonical registry with aliases, so that a feed param and a phrase cut out of a title
both arrive as the same attribute. The type, unit and rounding scale belong to the
attribute; whether it carries identity belongs to its pairing with a category.
"""

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.features.attributes.normalization import normalize_attribute_name

KEY = re.compile(r"^[a-z][a-z0-9_]*$")


class ValueType(StrEnum):
    ENUM = "enum"
    NUMBER = "number"
    BOOL = "bool"
    TEXT = "text"


class Origin(StrEnum):
    RULE = "rule"
    JUDGE = "judge"
    HUMAN = "human"


class AttributeBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    value_type: ValueType
    # Only for numbers: what the value is converted to, and how far it is rounded.
    unit_dimension: str | None = Field(default=None, max_length=20)
    scale: int | None = Field(default=None, ge=0, le=6)

    @model_validator(mode="after")
    def _units_are_for_numbers(self) -> "AttributeBase":
        if self.value_type is not ValueType.NUMBER and (
            self.unit_dimension is not None or self.scale is not None
        ):
            raise ValueError("unit_dimension and scale only apply to a number attribute")
        return self


class AttributeCreate(AttributeBase):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=64)

    @field_validator("key")
    @classmethod
    def _check_key(cls, value: str) -> str:
        lowered = value.strip().lower()
        if not KEY.match(lowered):
            raise ValueError("must be lowercase letters, digits and underscores")
        return lowered


class AttributeRead(AttributeBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str


class AliasCreate(BaseModel):
    """What a source calls this attribute."""

    model_config = ConfigDict(extra="forbid")

    alias: str = Field(min_length=1, max_length=200)
    language: str | None = Field(default=None, min_length=2, max_length=2)
    origin: Origin = Origin.HUMAN

    @field_validator("alias")
    @classmethod
    def _normalize_alias(cls, value: str) -> str:
        return normalize_attribute_name(value)

    @field_validator("language")
    @classmethod
    def _lower(cls, value: str | None) -> str | None:
        return None if value is None else value.lower()


class AliasRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    attribute_id: int
    alias_normalized: str
    language: str | None
    origin: Origin


class ValueCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical: str = Field(min_length=1, max_length=200)
    position: int = Field(default=0, ge=0)


class ValueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    attribute_id: int
    canonical: str
    position: int


class ValueAliasRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    attribute_value_id: int
    alias_normalized: str
    language: str | None
    origin: Origin


class CategoryAttributeCreate(BaseModel):
    """Attaching an attribute to a category, and saying what it means there."""

    model_config = ConfigDict(extra="forbid")

    attribute_id: int
    identity_bearing: bool = False
    position: int = Field(default=0, ge=0)
    label_override: str | None = Field(default=None, max_length=200)
    display_unit: str | None = Field(default=None, max_length=20)


class CategoryAttributeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_bearing: bool | None = None
    position: int | None = Field(default=None, ge=0)
    label_override: str | None = Field(default=None, max_length=200)
    display_unit: str | None = Field(default=None, max_length=20)


class CategoryAttributeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category_id: int
    attribute_id: int
    identity_bearing: bool
    position: int
    label_override: str | None
    display_unit: str | None
