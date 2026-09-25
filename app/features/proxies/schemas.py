"""Proxy schemas.

An address carries its credentials, `http://user:pass@host:port`, so every schema a caller
reads shows it masked, and only the worker's job carries it whole.
"""

from datetime import datetime
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.net import masked_url

SCHEMES = ("http", "https", "socks5", "socks5h")


def mask(url: str) -> str:
    return masked_url(url)


def _validate_urls(urls: list[str]) -> list[str]:
    cleaned = [url.strip() for url in urls]
    for url in cleaned:
        parts = urlsplit(url)
        if parts.scheme not in SCHEMES:
            raise ValueError(f"'{mask(url)}' is not one of {', '.join(SCHEMES)}")
        try:
            port = parts.port
        except ValueError as error:
            raise ValueError(f"'{mask(url)}' has a port that is not a number") from error
        if not parts.hostname or port is None:
            raise ValueError(f"'{mask(url)}' needs a host and a port")
        if parts.path not in ("", "/") or parts.query or parts.fragment:
            raise ValueError(f"'{mask(url)}' has more than scheme, credentials, host and port")
    if len(set(cleaned)) != len(cleaned):
        raise ValueError("the addresses must be distinct")
    return cleaned


class ProxyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    # Taken in turn by a run; one that stops answering is skipped for the rest of it.
    urls: list[str] = Field(min_length=1, max_length=50)
    is_enabled: bool = True
    note: str | None = Field(default=None, max_length=500)

    @field_validator("urls")
    @classmethod
    def _check(cls, value: list[str]) -> list[str]:
        return _validate_urls(value)


class ProxyUpdate(BaseModel):
    """Every field optional. `urls`, when sent, replaces the whole list: a masked address
    cannot be sent back, so the list is given again in full or not at all."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    urls: list[str] | None = Field(default=None, min_length=1, max_length=50)
    is_enabled: bool | None = None
    note: str | None = Field(default=None, max_length=500)

    @field_validator("urls")
    @classmethod
    def _check(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _validate_urls(value)


class ProxyRead(BaseModel):
    id: int
    name: str
    urls: list[str] = Field(description="Masked: the credentials are never shown")
    is_enabled: bool
    note: str | None
    sources: list[str] = Field(description="The channels going out through it, by slug")
    created_at: datetime
    updated_at: datetime


class AddressCheck(BaseModel):
    url: str = Field(description="Masked")
    ok: bool
    status: int | None = None
    ip: str | None = Field(None, description="The address the probe saw the request come from")
    ms: int | None = None
    error: str | None = None


class ProxyCheck(BaseModel):
    """Each address asked for the probe page once; what came back."""

    proxy_id: int
    probe: str
    addresses: list[AddressCheck]
