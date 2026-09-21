"""Schemas shared across endpoints."""

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str = Field(examples=["not_found"])
    message: str = Field(examples=["Product 42 not found"])
    details: Any | None = None


class ErrorResponse(BaseModel):
    """Every non-2xx response from this API has this shape."""

    error: ErrorDetail


class Page[T](BaseModel):
    """Simple offset-based page of items."""

    items: list[T]
    total: int = Field(description="Total number of items matching the query")
    limit: int
    offset: int


class HealthResponse(BaseModel):
    status: str = "ok"
    app: str
    version: str
    environment: str
