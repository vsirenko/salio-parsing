"""Shared pagination.

Two modes, one page shape:

- **offset** (`limit` + `offset`) for stable collections you page through by position;
- **cursor** (`limit` + `before_id`) for append-only feeds read newest-first. Offset
  paging drifts there: entries written between two requests push everything down, so
  page 2 repeats rows page 1 already showed. A cursor anchors to an id instead.

Endpoints pick a mode; the response shape is the same either way, so a client does not
have to care.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel, Field, computed_field

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


@dataclass(frozen=True)
class Pagination:
    """Validated paging request, passed from routes into services."""

    limit: int = DEFAULT_LIMIT
    offset: int = 0
    before_id: int | None = None
    # Set by the endpoint, not by the caller: it decides whether a next_cursor is
    # emitted. The first page of a cursor-paged feed has no before_id yet, so the
    # presence of an anchor cannot be what selects the mode.
    cursor_mode: bool = False
    # The order the caller asked for, already checked against the endpoint's allowed keys:
    # `(key, descending)` pairs, first key first. Empty means the endpoint's default.
    sort: tuple[tuple[str, bool], ...] = ()

    def slice[T](self, items: Sequence[T]) -> list[T]:
        """Apply the window. `before_id` has already filtered the input upstream."""
        return list(items[self.offset : self.offset + self.limit])


class Page[T](BaseModel):
    """Envelope returned by every list endpoint."""

    items: list[T]
    total: int = Field(
        description=(
            "Items matching the query. In cursor mode `before_id` counts as one of those "
            "filters, so this is what remains from the anchor, not the size of the whole feed."
        )
    )
    limit: int
    offset: int
    next_cursor: int | None = Field(
        default=None, description="Pass as before_id to fetch the next page (cursor mode)"
    )

    @computed_field(description="Whether another page exists")
    @property
    def has_more(self) -> bool:
        if self.next_cursor is not None:
            return True
        return self.offset + len(self.items) < self.total

    @classmethod
    def of(
        cls,
        items: Sequence[T],
        total: int,
        pagination: Pagination,
        *,
        cursor_field: str = "id",
    ) -> "Page[T]":
        """Build the envelope, deriving the next cursor when paging by cursor."""
        window = list(items)
        next_cursor = None
        if pagination.cursor_mode and window and total > pagination.offset + len(window):
            next_cursor = getattr(window[-1], cursor_field)

        return cls(
            items=window,
            total=total,
            limit=pagination.limit,
            offset=pagination.offset,
            next_cursor=next_cursor,
        )
