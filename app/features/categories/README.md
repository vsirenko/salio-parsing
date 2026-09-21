# categories

The tree products hang from, and the lever over what the storefront shows.

## Endpoints

| | |
|---|---|
| `GET /api/admin/categories` | list, filterable by `parent_id`, `roots_only`, `is_visible_effective` |
| `POST /api/admin/categories` | add one |
| `GET · PATCH /api/admin/categories/{id}` | read or edit |

No delete: a category products hang from cannot go, and one nothing hangs from costs nothing
to keep. Retiring a branch is what visibility is for.

Attaching attributes to a category lives in [attributes](../attributes/README.md), which
owns those routes.

## How it works

**Two states that have nothing to do with each other.** `is_visible` is editorial: hidden
means the storefront does not show it, while fetching continues, offers keep arriving and
nothing is deleted. `identity_ready` is technical: whether the parser can pull this
category's variant axes out of an offer. A category can be created and shown long before it
is ready — its variants simply take the slow path through the matcher.

**Visibility cascades.** Hiding a parent hides everything under it without editing a single
child, and unhiding restores the branch with its history rather than a hole in it.

**`is_visible_effective` is denormalized** and recomputed by one recursive statement over the
whole tree. Walking ancestors per query does not survive millions of variants, and a
storefront filter has to be a boolean on an index rather than a recursion. Recomputing
everything rather than the moved subtree is deliberate: it cannot leave a stale branch behind
the way a clever partial update can.

It cannot be set by hand. Accepting it would let a caller write a value the next recompute
silently overrules.

**A category cannot become its own descendant.** The move is refused, or the branch would
close a loop and detach itself from every root.

## Decisions worth knowing before changing it

- The slug is entered, never derived from the name, so a rename does not move the URL.
- Visibility is one flag for all markets. A category empty in Lithuania hides itself from a
  refreshed offer count rather than a second flag per market — that would multiply the
  editorial work by the number of markets to express something the data already knows. The
  count is not built yet; see `TODO.md`.
- An unmapped source category is not dropped: it lands in an `uncategorized` category that
  happens to be hidden, so nothing half-understood reaches the storefront and nothing is lost.
  That mapping is part of the parser and does not exist yet.

See also `docs/parser-design.md`, "Categories and visibility".
