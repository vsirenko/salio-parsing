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

    labels: dict[str, str] = {}

    @field_validator("labels")
    @classmethod
    def _labels(cls, value: dict[str, str]) -> dict[str, str]:
        return _clean_labels(value) or {}

    key: str = Field(min_length=1, max_length=64)

    @field_validator("key")
    @classmethod
    def _check_key(cls, value: str) -> str:
        lowered = value.strip().lower()
        if not KEY.match(lowered):
            raise ValueError("must be lowercase letters, digits and underscores")
        return lowered


# A language code, and what a person reads in it.
Labels = dict[str, str]


def _clean_labels(value: Labels | None) -> Labels | None:
    """Two-letter lower-case languages, and no empty text: a blank label is no label."""
    if value is None:
        return None
    cleaned: Labels = {}
    for language, text in value.items():
        code = language.strip().lower()
        if len(code) != 2 or not code.isalpha():
            raise ValueError(f"'{language}' is not a two-letter language code")
        if text and text.strip():
            cleaned[code] = text.strip()
    return cleaned


class AttributeRead(AttributeBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    labels: Labels = Field(description="What a person reads, by language; falls back to `name`")


# What a list of attributes may be sorted by, `?sort=`.
ATTRIBUTE_SORT = (
    "id",
    "key",
    "name",
    "categories_count",
    "values_count",
    "aliases_count",
    "variants_count",
)


class AttributeRow(AttributeRead):
    """An attribute with where it is used and how far it is set up."""

    categories_count: int = Field(description="Categories it is bound to")
    values_count: int = Field(description="Canonical values; an enum's only")
    aliases_count: int = Field(description="Names shops give it")
    variants_count: int = Field(description="Entries that carry a value of it")


class AttributeUpdate(BaseModel):
    """The name and the labels, always; the unit and the scale only while nothing is stored.

    The key is not here: the readings and the rules name an attribute by it. A stored number
    means what its unit says it means — `storage_mb` holds `16384` — and relabelling the
    unit under it would make every stored value a different amount.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    labels: Labels | None = None
    unit_dimension: str | None = Field(default=None, max_length=20)
    scale: int | None = Field(default=None, ge=0, le=6)

    @field_validator("labels")
    @classmethod
    def _labels(cls, value: Labels | None) -> Labels | None:
        return _clean_labels(value)


class AttributeCategoryRead(BaseModel):
    """A category an attribute is bound to, and what that category makes of it."""

    category_id: int
    category_name: str
    category_slug: str
    identity_bearing: bool
    position: int
    label_override: str | None
    display_unit: str | None


class ValueResolution(BaseModel):
    """What the registry makes of a string, for this attribute."""

    query: str
    normalized: str
    is_attribute_name: bool = Field(description="The string is a name a shop gives the attribute")
    value: "ValueRead | None" = Field(description="The value the string resolves to, if any")
    via: str | None = Field(description="`canonical` or `alias`: how it resolved")


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
    labels: Labels = {}

    @field_validator("labels")
    @classmethod
    def _labels(cls, value: Labels) -> Labels:
        return _clean_labels(value) or {}


class ValueAliasRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    attribute_value_id: int
    alias_normalized: str
    language: str | None
    origin: Origin


class ValueRead(BaseModel):
    """A canonical value, what shops call it, and how many entries carry it — a value no
    entry carries and no reading produces is one to look at."""

    id: int
    attribute_id: int
    canonical: str
    position: int
    labels: Labels = Field(
        description="What a person reads, by language; falls back to `canonical`"
    )
    aliases: list[ValueAliasRead] = []
    variants_count: int = 0


class ValueUpdate(BaseModel):
    """The order and the labels. The canonical string is what the readings produce and the
    matcher looks up — `wifi`, `Intel Core Ultra 5 226V` — so it is never renamed here; a
    value that reads badly gets a label."""

    model_config = ConfigDict(extra="forbid")

    position: int | None = Field(default=None, ge=0)
    labels: Labels | None = None

    @field_validator("labels")
    @classmethod
    def _labels(cls, value: Labels | None) -> Labels | None:
        return _clean_labels(value)


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


class AttributeRef(BaseModel):
    """The attribute a binding is of, as a table row needs it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    name: str
    value_type: str
    unit_dimension: str | None
    labels: dict[str, str] = {}


class CategoryAttributeRead(BaseModel):
    """An attribute bound to a category, the attribute named: a row can print `RAM`."""

    category_id: int
    attribute_id: int
    attribute: AttributeRef
    identity_bearing: bool
    position: int
    label_override: str | None
    display_unit: str | None
