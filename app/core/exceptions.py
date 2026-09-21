"""Domain-level exceptions. Services raise these; the API layer never builds HTTP errors itself."""

from typing import Any


class AppError(Exception):
    """Base class for expected, client-visible errors."""

    status_code: int = 500
    code: str = "internal_error"
    message: str = "Internal server error"
    # Response headers the error needs to carry, e.g. Retry-After on a 429. The single
    # error handler applies them; subclasses do not build responses themselves.
    headers: dict[str, str] | None = None

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details
        self.headers = headers or self.headers
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


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many attempts. Try again later."

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            details={"retry_after": retry_after},
            headers={"Retry-After": str(retry_after)},
        )
