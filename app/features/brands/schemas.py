"""Brand schemas."""

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.features.brands.normalization import normalize_brand

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


class BrandMatch(BaseModel):
    """What a string resolves to. More than one row means the string is ambiguous."""

    brand: BrandRead
    matched_alias: str
    kind: AliasKind
