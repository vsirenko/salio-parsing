"""Pagination query parameters as reusable dependencies.

Defined as factories so an endpoint can widen the cap where it is justified, without
every route restating the bounds.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Query

from app.schemas.pagination import DEFAULT_LIMIT, MAX_LIMIT, Pagination


def pagination_params(
    *, default_limit: int = DEFAULT_LIMIT, max_limit: int = MAX_LIMIT
) -> Callable[..., Pagination]:
    """Offset paging: `?limit=&offset=`."""

    def dependency(
        limit: Annotated[int, Query(ge=1, le=max_limit)] = default_limit,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> Pagination:
        return Pagination(limit=limit, offset=offset)

    return dependency


def cursor_pagination_params(
    *, default_limit: int = DEFAULT_LIMIT, max_limit: int = MAX_LIMIT
) -> Callable[..., Pagination]:
    """Cursor paging: `?limit=&before_id=`, with offset kept for one-off jumps."""

    def dependency(
        limit: Annotated[int, Query(ge=1, le=max_limit)] = default_limit,
        offset: Annotated[int, Query(ge=0)] = 0,
        before_id: Annotated[
            int | None,
            Query(ge=1, description="Return entries older than this id. Use next_cursor."),
        ] = None,
    ) -> Pagination:
        return Pagination(limit=limit, offset=offset, before_id=before_id, cursor_mode=True)

    return dependency
