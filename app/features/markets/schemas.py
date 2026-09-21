"""Market schemas.

A market is a country we have decided to sell in — not every country we can describe.
The country reference table holds those; this holds the storefronts.
"""

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
LANGUAGE = re.compile(r"^[a-z]{2}$")


def _validate_slug(value: str) -> str:
    if not SLUG.match(value):
        raise ValueError("must be lowercase letters, digits and single hyphens")
    return value


def _validate_languages(value: list[str]) -> list[str]:
    lowered = [item.strip().lower() for item in value]
    if not lowered:
        raise ValueError("a market needs at least one language")
    for item in lowered:
        if not LANGUAGE.match(item):
            raise ValueError(f"'{item}' is not an ISO 639-1 code")
    if len(set(lowered)) != len(lowered):
        raise ValueError("languages must be distinct")
    return lowered


class MarketBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    # The path segment. Entered rather than derived from the name: deriving it would let
    # a rename move the URL, and this is the slug whose change moves every page of a
    # storefront rather than one.
    slug: str = Field(min_length=1, max_length=32)
    # Ordered; the first is the default. Latvia reading in Russian is this list, not a
    # second market — the prices and the shops are the same either way.
    languages: list[str] = Field(min_length=1, max_length=10)
    is_enabled: bool = False

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, value: str) -> str:
        return _validate_slug(value)

    @field_validator("languages")
    @classmethod
    def _check_languages(cls, value: list[str]) -> list[str]:
        return _validate_languages(value)


class MarketCreate(MarketBase):
    """Opening a storefront. Disabled unless asked otherwise: a market is created, wired
    into the parsers, mapped, and only then shown."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=2, max_length=2)

    @field_validator("code")
    @classmethod
    def _uppercase(cls, value: str) -> str:
        return value.upper()


class MarketRead(MarketBase):
    model_config = ConfigDict(from_attributes=True)

    code: str


class MarketUpdate(BaseModel):
    """Every field optional; only what is sent is applied.

    The code is the identity and is not editable — a market in another country is
    another market.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    slug: str | None = Field(default=None, min_length=1, max_length=32)
    languages: list[str] | None = Field(default=None, min_length=1, max_length=10)
    is_enabled: bool | None = None

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, value: str | None) -> str | None:
        return None if value is None else _validate_slug(value)

    @field_validator("languages")
    @classmethod
    def _check_languages(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _validate_languages(value)
