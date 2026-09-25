# markets

The storefronts we run. Latvia first, then Lithuania and Estonia.

## Endpoints

| | |
|---|---|
| `GET /api/admin/markets` | list, filterable by `is_enabled`, with its counts |
| `POST /api/admin/markets` | open one |
| `GET /api/admin/markets/languages` | the ISO 639-1 codes `languages` accepts, with names |
| `GET · PATCH /api/admin/markets/{code}` | read or edit — mainly `is_enabled` |

Which shops a market holds is asked of the shops: `GET /api/admin/shops?market_code=LV`
with `market_state=shown` (the default), `hidden` or `attached`, and each shop row names
the markets it is shown in (`markets`) and attached to but hidden from (`hidden_markets`).
Attaching and showing is `PUT /api/admin/shops/{id}/markets/{code}`.

## How it works

**A market is a country we have decided to sell in.** The country code is the primary key
*and* the foreign key, so two markets in one country are impossible by construction rather
than by convention. It is also what `offer` and `price_event` will carry, where two
characters instead of an eight-byte id is worth a couple of gigabytes.

**`slug` is the path segment**, kept separate from the code because the URL is a product
decision and the ISO code is not: `/lv/` or `/latvija/`, whichever reads better. Entered
rather than derived from the name — deriving it would let a rename move the URL.

**`languages` is an ordered list, and the first is the default.** A language is not a
market: Latvia read in Russian is the same prices, the same shops and the same delivery, so
it is a toggle here rather than a second storefront.

**Every market row carries its counts** — shops shown and attached, listings on sale, visible
families — so a list of markets is one request rather than two more per row. They are the
storefront's view: a listing counts where its shop is *shown*, because an attached shop
that is still hidden sells nothing there yet. On sale means what the pipeline counts by
(`offer_is_listed`), and a family counts when it is visible and has a new listing on sale.

**A language is an ISO 639-1 code, checked against the list**, not only its shape:
`[a-z]{2}` let `xx` through. The list is `app/core/languages.py` — a standard, kept as a
constant the way GS1's prefixes are.

**`is_enabled` defaults to false.** A market is created, wired into the parsers, its
categories mapped, and only then shown. That is what makes adding Lithuania a process rather
than a release.

## Decisions worth knowing before changing it

- Nothing is seeded. Countries and currencies are facts about the world and belong in a
  migration; opening a market is a decision and goes through the POST.
- **Changing a live market's slug moves every URL of that storefront**, not one page. There
  is no redirect table, so until there is, treat it as fixed.
- One storefront per country is assumed. A market spanning several countries would be a real
  modelling change, not a column — deliberately deferred until there is a reason.

See also `docs/parser-design.md`, "Markets, shops and where money is charged".
