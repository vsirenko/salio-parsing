"""Pagination query parameters as reusable dependencies.

Defined as factories so an endpoint can widen the cap where it is justified, without
every route restating the bounds.
"""

from collections.abc import Callable, Sequence
from typing import Annotated

from fastapi import Query

from app.core.exceptions import ValidationError
from app.schemas.pagination import DEFAULT_LIMIT, MAX_LIMIT, Pagination


def pagination_params(
    *,
    default_limit: int = DEFAULT_LIMIT,
    max_limit: int = MAX_LIMIT,
    sortable: Sequence[str] = (),
    default_sort: str = "",
) -> Callable[..., Pagination]:
    """Offset paging: `?limit=&offset=`, and `?sort=` where the endpoint names what sorts.

    `sort` is a comma-separated list of the endpoint's keys, a leading `-` for descending:
    `sort=-created_at,title`. A key the endpoint does not allow is a 422, never silently
    ignored — a page that looks sorted and is not is worse than an error. The id always
    breaks ties last (see `ordered`), so offset pages cannot swap rows between requests.
    """
    if not sortable:

        def dependency(
            limit: Annotated[int, Query(ge=1, le=max_limit)] = default_limit,
            offset: Annotated[int, Query(ge=0)] = 0,
        ) -> Pagination:
            return Pagination(limit=limit, offset=offset)

        return dependency

    allowed = ", ".join(sortable)

    def sorted_dependency(
        limit: Annotated[int, Query(ge=1, le=max_limit)] = default_limit,
        offset: Annotated[int, Query(ge=0)] = 0,
        sort: Annotated[
            str | None,
            Query(
                max_length=200,
                description=f"Comma-separated, `-` for descending. Allowed: {allowed}.",
                examples=[default_sort or sortable[0]],
            ),
        ] = None,
    ) -> Pagination:
        return Pagination(
            limit=limit, offset=offset, sort=_sort_keys(sort or default_sort, sortable)
        )

    return sorted_dependency


def _sort_keys(value: str, sortable: Sequence[str]) -> tuple[tuple[str, bool], ...]:
    keys: list[tuple[str, bool]] = []
    for part in (p.strip() for p in value.split(",")):
        if not part:
            continue
        descending = part.startswith("-")
        key = part.lstrip("-+")
        if key not in sortable:
            raise ValidationError(
                f"Cannot sort by '{key}'",
                code="unknown_sort_key",
                details={"allowed": list(sortable)},
            )
        if key not in (k for k, _ in keys):
            keys.append((key, descending))
    return tuple(keys)


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
