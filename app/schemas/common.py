"""Schemas shared across endpoints. Pagination lives in schemas/pagination.py."""

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str = Field(examples=["not_found"])
    message: str = Field(examples=["Product 42 not found"])
    details: Any | None = None


class ErrorResponse(BaseModel):
    """Every non-2xx response from this API has this shape."""

    error: ErrorDetail


class HealthResponse(BaseModel):
    status: str = "ok"
    app: str
    version: str
    environment: str
