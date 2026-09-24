"""Category schemas.

The tree products hang from. Visibility is editorial and cascades; `identity_ready` is
technical and says whether the parser can pull this category's variant axes out of an
offer. The two are independent on purpose — a category can be shown before it is ready.
"""

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.features.categories.normalization import normalize_category_name

SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _validate_slug(value: str) -> str:
    if not SLUG.match(value):
        raise ValueError("must be lowercase letters, digits and single hyphens")
    return value


class CategoryBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_id: int | None = None
    is_visible: bool = True
    identity_ready: bool = False
    # The model rung places a listing only on an entry that agrees on every identity axis.
    model_match_needs_full_identity: bool = False


class CategoryCreate(CategoryBase):
    model_config = ConfigDict(extra="forbid")

    # Entered rather than derived from the name: a rename must not move the URL.
    slug: str = Field(min_length=1, max_length=64)

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, value: str) -> str:
        return _validate_slug(value)


class CategoryRead(CategoryBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    # Own visibility and every ancestor's. Derived, never sent in.
    is_visible_effective: bool


class AliasOrigin(StrEnum):
    RULE = "rule"
    JUDGE = "judge"
    HUMAN = "human"


class CategoryAliasCreate(BaseModel):
    """A name a shop gives this category, in the language it gives it in."""

    model_config = ConfigDict(extra="forbid")

    alias: str = Field(min_length=1, max_length=200)
    language: str | None = Field(default=None, min_length=2, max_length=2)
    origin: AliasOrigin = AliasOrigin.HUMAN

    @field_validator("alias")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return normalize_category_name(value)

    @field_validator("language")
    @classmethod
    def _lower(cls, value: str | None) -> str | None:
        return None if value is None else value.lower()


class CategoryAliasRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_id: int
    alias_normalized: str
    language: str | None
    origin: AliasOrigin


class CategoryUpdate(BaseModel):
    """Every field optional; only what is sent is applied.

    `is_visible_effective` is not here — it is computed from the tree, and accepting it
    would let a caller write a value the next recompute silently overrules.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=64)
    parent_id: int | None = None
    is_visible: bool | None = None
    model_match_needs_full_identity: bool | None = None
    identity_ready: bool | None = None

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, value: str | None) -> str | None:
        return None if value is None else _validate_slug(value)
