# products

The original resource this service was built around: a flat product list with a price.

## Endpoints

| | |
|---|---|
| `GET /api/products` | list, filterable by `search` and `in_stock` |
| `POST /api/products` | create |
| `GET /api/products/{id}` | get one |

## How it works

Nothing surprising: route → service → schema, offset paging through the shared `Page[T]`
envelope, `Decimal` for money. Names are unique case-insensitively, enforced by a functional
unique index rather than by the service.

## Decisions worth knowing before changing it

- **`POST` is open to everyone.** Auth exists and was never applied here. That is a known
  hole, not a decision — see `TODO.md`.
- This is **not** the catalogue the parser will build. That one is `product` and `variant` as
  described in `docs/parser-design.md`, where a variant is the primary entity and an offer
  attaches to it. This feature predates that design and will either be replaced by it or
  turned into a thin read of it; do not extend it as though it were the catalogue.
