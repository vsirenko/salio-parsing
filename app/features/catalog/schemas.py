"""Catalogue schemas: the family, the thing that is bought, and what is known about it."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VariantKind(StrEnum):
    SINGLE = "single"
    # N of one thing. Comparable with the single item once divided.
    MULTIPACK = "multipack"
    # Different things together. Stays out of the single item's price comparison —
    # listing a phone-with-case as the cheapest phone would be a lie.
    BUNDLE = "bundle"


class ValueOrigin(StrEnum):
    CONSENSUS = "consensus"
    HUMAN = "human"


class SourceKind(StrEnum):
    PARAM = "param"
    TITLE = "title"


class IdentifierOrigin(StrEnum):
    RULE = "rule"
    JUDGE = "judge"
    HUMAN = "human"


# --- product ---


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_id: int
    category_id: int
    model: str = Field(min_length=1, max_length=200)
    description: str | None = None
    manufacturer_url: str | None = Field(default=None, max_length=1000)


class ProductUpdate(BaseModel):
    """`title` and `slug` are absent on purpose — both are derived.

    A generated title is corrected through `title_override`, which survives the next
    regeneration. Accepting the title itself would let a caller write a value the next
    model change silently overwrites.
    """

    model_config = ConfigDict(extra="forbid")

    model: str | None = Field(default=None, min_length=1, max_length=200)
    category_id: int | None = None
    title_override: str | None = Field(default=None, max_length=400)
    description: str | None = None
    manufacturer_url: str | None = Field(default=None, max_length=1000)
    is_visible: bool | None = None


# What a list of families may be sorted by, `?sort=`.
PRODUCT_SORT = (
    "id",
    "title",
    "created_at",
    "brand",
    "variants_count",
    "offers_count",
    "shops_count",
    "min_price",
)
# And a list of entries.
VARIANT_SORT = ("id", "title", "created_at", "brand", "offers_count", "shops_count", "min_price")


class BrandRef(BaseModel):
    """A brand as a row names it: enough to print and to link, nothing to edit."""

    id: int
    canonical_name: str


class CategoryRef(BaseModel):
    id: int
    name: str


class ProductRef(BaseModel):
    """The family an entry belongs to."""

    id: int
    title: str


class ProductRead(BaseModel):
    """A family, with what a list of them needs to be read without further requests.

    The brand and the category come named, so a table shows `Lenovo` rather than `#15`, and
    three counts say whether the family is comparable at all: how many entries it holds,
    how many listings on sale new are placed on them and at how many shops, and the lowest
    price any of them asks.
    """

    id: int
    slug: str
    brand: BrandRef
    category: CategoryRef
    model: str
    title: str
    title_override: str | None
    description: str | None
    manufacturer_url: str | None
    is_visible: bool
    created_at: datetime
    variants_count: int = Field(description="Catalogue entries in the family")
    offers_count: int = Field(description="New listings on sale placed on one of them")
    shops_count: int = Field(description="Shops those listings are at")
    min_price: Decimal | None = Field(
        description="The lowest price of those listings, in the shop's currency (EUR)"
    )


# --- variant ---


class VariantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_id: int
    category_id: int
    model: str = Field(min_length=1, max_length=200)
    # Nullable: a variant that matched nothing does not belong to a family yet, and
    # inventing one from a single data point would be a guess.
    product_id: int | None = None
    kind: VariantKind = VariantKind.SINGLE
    unit_count: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _only_multipacks_count(self) -> "VariantCreate":
        if (self.kind is VariantKind.MULTIPACK) != (self.unit_count > 1):
            raise ValueError("unit_count above one means a multipack, and nothing else")
        return self


class VariantUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int | None = None
    model: str | None = Field(default=None, min_length=1, max_length=200)
    category_id: int | None = None
    kind: VariantKind | None = None
    unit_count: int | None = Field(default=None, ge=1)
    title_override: str | None = Field(default=None, max_length=400)
    description: str | None = None
    # Taken from an offer by default; set here it is pinned and survives the next crawl.
    image_url_override: str | None = Field(default=None, max_length=1000)
    is_visible: bool | None = None


class VariantAttributeShown(BaseModel):
    """One thing known about an entry, as its category shows it.

    The label is the category's own for the attribute, else the attribute's name; the order
    is the category's; `display` is the value as a title prints it — `16 GB`, `13.6"` — in
    the attribute's unit. `value` is the stored one, for a front end that formats its own.
    """

    key: str
    label: str
    value: bool | int | float | str
    display: str
    unit: str | None
    position: int | None
    identity_bearing: bool


class VariantRead(BaseModel):
    """An entry — the thing that is bought — with what a list of them needs.

    Named brand, category and family; the axes it is told apart by, so the entries of one
    family are not rows with one title; and what it sells for now.
    """

    id: int
    slug: str
    product: ProductRef | None
    brand: BrandRef
    category: CategoryRef
    model: str
    model_normalized: str
    title: str
    title_override: str | None
    description: str | None
    image_url: str | None
    image_url_override: str | None
    kind: VariantKind
    unit_count: int
    # Null means an identity-bearing attribute of the category is missing, so this variant
    # takes the long way round through the matcher rather than a hash lookup.
    identity_key: str | None
    is_visible: bool
    created_at: datetime
    axes: dict[str, bool | int | float | str] = Field(
        description='What is known about it, by attribute key: `{"cpu": "Intel Core Ultra 5'
        ' 226V", "ram_mb": 16384}`'
    )
    attributes: list[VariantAttributeShown] = Field(
        description="The same, labelled and ordered as its category shows them"
    )
    offers_count: int = Field(description="New listings on sale placed on it")
    shops_count: int = Field(description="Shops those listings are at")
    min_price: Decimal | None = Field(description="The lowest of their prices (EUR)")


# --- what is known about a variant ---


class VariantAttributeSet(BaseModel):
    """Exactly one value, matching the attribute's type."""

    model_config = ConfigDict(extra="forbid")

    attribute_id: int
    value_num: Decimal | None = None
    value_id: int | None = None
    value_bool: bool | None = None
    value_text: str | None = None
    source_kind: SourceKind = SourceKind.PARAM
    origin: ValueOrigin = ValueOrigin.HUMAN

    @model_validator(mode="after")
    def _exactly_one(self) -> "VariantAttributeSet":
        given = [
            v
            for v in (self.value_num, self.value_id, self.value_bool, self.value_text)
            if v is not None
        ]
        if len(given) != 1:
            raise ValueError("give exactly one of value_num, value_id, value_bool, value_text")
        return self


class VariantAttributeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    variant_id: int
    attribute_id: int
    value_num: Decimal | None
    value_id: int | None
    value_bool: bool | None
    value_text: str | None
    source_kind: SourceKind
    origin: ValueOrigin


class IdentifierCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1, max_length=100)
    origin: IdentifierOrigin = IdentifierOrigin.HUMAN


class VariantGtinRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    variant_id: int
    gtin: str
    origin: IdentifierOrigin
    first_seen_at: datetime


class VariantMpnRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    variant_id: int
    brand_id: int
    mpn_raw: str
    mpn_normalized: str
    origin: IdentifierOrigin
    first_seen_at: datetime
