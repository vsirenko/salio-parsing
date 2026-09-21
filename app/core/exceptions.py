"""Domain-level exceptions. Services raise these; the API layer never builds HTTP errors itself."""

from typing import Any


class AppError(Exception):
    """Base class for expected, client-visible errors."""

    status_code: int = 500
    code: str = "internal_error"
    message: str = "Internal server error"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: Any | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "Resource not found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "Resource already exists"


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"
    message = "Invalid request payload"
