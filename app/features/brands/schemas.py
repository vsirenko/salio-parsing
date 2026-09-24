"""Brand schemas."""

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.features.brands.normalization import (
    LONGEST_MODEL_NAME,
    normalize_brand,
    normalize_model_name,
)

SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class AliasKind(StrEnum):
    """Where an alias may be read from.

    Not how confident we are — that is `origin`. This says whether the string may be
    trusted outside a feed's brand field.
    """

    # Another way of writing the brand. Safe anywhere: the brand field and the title.
    SPELLING = "spelling"
    # A line the brand makes: iPhone, Galaxy, MacBook. The brand field only — a title
    # saying "case for iPhone 15" is not an Apple product.
    LINE = "line"


class Origin(StrEnum):
    RULE = "rule"
    JUDGE = "judge"
    HUMAN = "human"


class BrandBase(BaseModel):
    # Deliberately not unique: Delta is taps and machine tools, two companies sharing a
    # name. The slug is what separates them.
    canonical_name: str = Field(min_length=1, max_length=200)


class BrandCreate(BrandBase):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=64)

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, value: str) -> str:
        if not SLUG.match(value):
            raise ValueError("must be lowercase letters, digits and single hyphens")
        return value


class BrandRead(BrandBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str


# What a list of brands may be sorted by, `?sort=`.
BRAND_SORT = (
    "id",
    "name",
    "products_count",
    "variants_count",
    "offers_count",
    "aliases_count",
    "models_count",
)
# What `has_*` filters exist, each keyed to the count it tests.
BRAND_HAS = {
    "products": "products_count",
    "variants": "variants_count",
    "offers": "offers_count",
    "aliases": "aliases_count",
    "models": "models_count",
}


class BrandRow(BrandRead):
    """A brand with how much of the catalogue it holds and how far it is set up.

    `offers_count` counts new listings on sale placed on its entries, the rule the catalogue's
    counts go by. A brand with no aliases resolves no shop's string; one with no products is
    either new or left over from a merge, and both are worth finding.
    """

    products_count: int
    variants_count: int
    offers_count: int = Field(description="New listings on sale placed on its entries")
    aliases_count: int = Field(description="Spellings that resolve to it")
    models_count: int = Field(description="Model names entered for it, in every category")


class BrandUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, value: str | None) -> str | None:
        if value is not None and not SLUG.match(value):
            raise ValueError("must be lowercase letters, digits and single hyphens")
        return value


class BrandAliasCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias: str = Field(min_length=1, max_length=200)
    kind: AliasKind = AliasKind.SPELLING
    origin: Origin = Origin.HUMAN

    @field_validator("alias")
    @classmethod
    def _normalizable(cls, value: str) -> str:
        # Rejected here rather than stored empty: an alias that normalizes to nothing
        # would match every offer whose brand field is a stray punctuation mark.
        normalize_brand(value)
        return value


class BrandAliasRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    brand_id: int
    alias_normalized: str
    alias_raw: str
    kind: AliasKind
    origin: Origin


class ModelAliasCreate(BaseModel):
    """One way a shop writes a model, and the spelling the catalogue uses for it.

    `alias` is what is found in a title; `model` is what the reading comes out as. Adding
    the canonical spelling as an alias of itself is the usual first row, and the one the
    seed writes — a name that is only a target is never found.
    """

    model_config = ConfigDict(extra="forbid")

    # Which kind of product the name is for. A maker names its phones and its tablets
    # differently, and a name entered for one must not be read into the other.
    category_id: int
    alias: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=200)
    origin: Origin = Origin.HUMAN

    @field_validator("alias")
    @classmethod
    def _a_name_not_a_title(cls, value: str) -> str:
        # Rejected here rather than stored and never found: the reader looks up windows of
        # at most `LONGEST_MODEL_NAME` words, so a longer alias would sit in the table and
        # match nothing. Anything that long is a spec sheet, not a name.
        words = normalize_model_name(value).split()
        if len(words) > LONGEST_MODEL_NAME:
            raise ValueError(f"a model name is at most {LONGEST_MODEL_NAME} words")
        return value

    @field_validator("model")
    @classmethod
    def _spelled(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class ModelAliasRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    brand_id: int
    category_id: int
    alias_normalized: str
    model: str
    origin: Origin


class BrandMatch(BaseModel):
    """What a string resolves to. More than one row means the string is ambiguous."""

    brand: BrandRead
    matched_alias: str
    kind: AliasKind
