# categories

The tree products hang from, and the lever over what the storefront shows.

## Endpoints

| | |
|---|---|
| `GET /api/admin/categories` | list with counts, filterable by `parent_id`, `roots_only`, `is_visible_effective`, `search`, `ids`; `?sort=` |
| `GET /api/admin/categories/tree` | the whole tree, nested, with each branch's totals |
| `POST /api/admin/categories` | add one |
| `GET · PATCH /api/admin/categories/{id}` | read or edit |
| `GET /api/admin/categories/{id}/aliases` | what shops call this category |
| `POST /api/admin/categories/{id}/aliases` | add a name a shop gives it |
| `DELETE /api/admin/categories/{id}/aliases/{alias_id}` | stop reading a name as it |

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

**`model_match_needs_full_identity` is a matching setting, and it is the category's to
make** because what a model string names depends on the kind of thing. A phone's model
covers a handful of capacities and colours, and the model rung may place a listing on the one
entry that agrees on the axes both happen to carry. A laptop's covers dozens of
configurations: on bigbox's first laptop run, 234 of 392 model matches were made that way and
some were plainly wrong. With the flag on, the rung places by model only when every identity
axis is known on both sides and equal; what is left goes on as unmatched, and a listing with
a barcode becomes an entry of its own. Off by default, on for laptops.

**A row counts what the category holds and how far it is set up**: products, variants,
offers (new listings on sale on its entries, the catalogue's rule), children, aliases and
attributes — its own, not its branch's. `GET /categories/tree` hands the whole tree over at
once, each node with its children and its branch's totals (`branch_products_count`, …):
there are few categories, and paging a hundred at a time to build a tree or a filter was the
alternative. `search` finds a category by its name, its slug or a name a shop gives it.

**Visibility cascades.** Hiding a parent hides everything under it without editing a single
child, and unhiding restores the branch with its history rather than a hole in it.

**`is_visible_effective` is denormalized** and recomputed by one recursive statement over the
whole tree. Walking ancestors per query does not survive millions of variants, and a
storefront filter has to be a boolean on an index rather than a recursion. Recomputing
everything rather than the moved subtree is deliberate: it cannot leave a stale branch behind
the way a clever partial update can.

It cannot be set by hand. Accepting it would let a caller write a value the next recompute
silently overrules.

**A category has the names shops give it.** `category_aliases` holds one row per spelling,
normalized the way it will be looked up: `„Telefons“`, `Telefons,` and `telefons` are one
row. Diacritics survive — folding `tālrunis` to `talrunis` merges words that only look alike
to somebody who does not read the language.

The table does two jobs, and either one alone would have justified it:

- **The word at the front of a title.** `Telefons Apple iPhone 18 Pro Max 256GB Burgundy` —
  a shop that states no model states one here, in front of the brand, and cutting it off is
  how the model is read. The words are Latvian, so they cannot live in a Python tuple: the
  same rule has to serve a Lithuanian shop, and that is rows, not a code change.
- **The name of the section a listing came from**, for the source-category mapping that is
  designed and unbuilt (`docs/parser-design.md`). It needs exactly this table.

Reading uses `Vocabulary` (`app/features/offers/normalization/rules.py`) rather than a query
from inside a rule: normalization is a pure function of the payload and the words handed to
it, which is what lets a reading be recomputed and compared. `OfferService` loads the words
once per category and passes them in.

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
