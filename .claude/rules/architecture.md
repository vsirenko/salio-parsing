## Architecture
- Flow is strictly route → service → schema. Routes contain no business logic.
- Do not add repository pattern, CQRS, event bus, DI containers or service locators.
  Keep new code as flat as what is already there.
- Services raise `AppError` subclasses from `app/core/exceptions.py`. Routes never build
  HTTP errors themselves — `app/core/error_handlers.py` turns them into the single
  `{"error": {"code", "message", "details"}}` envelope. A new error type is a new
  subclass, not a new handler. An error that needs a response header — `Retry-After` on
  a 429 — sets `headers` on its subclass and the one handler applies them.
- Money is `Decimal`, never float.
- Rates and shares are stored as fractions, never percentages: `0.2100`, not `21`. They
  get multiplied, and percentages scatter a `/ 100` through the code until one of them is
  forgotten.
- The tree is sliced by feature, not by layer. Everything one feature needs sits in
  `app/features/<name>/`:

  ```
  app/
    main.py                 app assembly, middleware, lifespan
    api/                    wiring only: deps.py, pagination.py, router.py,
                            admin_router.py — no routes of its own
    core/                   cross-cutting and feature-agnostic: config, logging,
                            security (passwords, JWT), exceptions, error_handlers,
                            audit context, net
    db/                     base, models, session, query — every model in models.py
    schemas/                only envelopes shared by every feature: Page, ErrorResponse
    features/               each one with a README.md of its own
      users/                router.py  admin_router.py  service.py  schemas.py
      brands/               admin_router.py  service.py  schemas.py  normalization.py
      categories/           admin_router.py  service.py  schemas.py
      attributes/           admin_router.py  service.py  schemas.py
      countries/ currencies/ markets/        reference data
      audit/                router.py  service.py  schemas.py  middleware.py
      rate_limit/           service.py
      pipeline/             admin_router.py  service.py  schemas.py  (read-only counts)
      health/               router.py
  ```

- New resource = a folder under `app/features/`, holding `schemas.py`, `service.py` and
  `router.py` (plus `admin_router.py` if the admin panel touches it), then mounted in
  `app/api/router.py` or `app/api/admin_router.py`. Mount it nowhere else.
- Imports point one way: `features` may import `core`, `db` and `schemas`; those three
  never import a feature. `api` wires features together and may import any of them.
  `tests/test_architecture.py` enforces this — it fails on a new violation.
- Reading another feature's table is not a cross-feature import. Every model lives in
  `app/db/models.py`, so a service selects from whatever table it needs; only importing
  another feature's service, schemas or router counts as reaching across.
- One feature imports another only where that other one is infrastructure for the rest:
  `users/service.py` uses `rate_limit/service.py`, and that is the whole list. A new
  cross-feature import is a design question, not a detail; answer it, then add it to the
  allowed set in that test with the answer written down.
- A feature folder holds what that feature needs and nothing more. `rate_limit` has no
  router because nothing exposes it; `health` has no service because it has no state.
- **Every feature folder holds a `README.md`, and changing the feature means changing it
  in the same commit.** Not a summary of the code — the code is already there. It answers
  what the feature exposes, how it works, and which decision somebody would otherwise get
  wrong: the reasoning that is invisible in a diff and expensive to rediscover. A change
  that makes the README wrong is not finished.
- That README is where a decision is written down. `.claude/rules/` holds what applies
  everywhere, `docs/parser-design.md` holds what is designed but unbuilt, and a feature's
  README holds what is true of that feature now. When the same thing would fit two of
  them, it goes in the narrowest one and the others link to it.
- `tests/test_architecture.py` enforces what it can: every feature has a README, and the
  endpoint tables in one are checked against the live routes by method and path. Prose is
  not checkable — that part is on whoever edits the feature.
- Service methods stay `async` even while storage is in-memory, so swapping in a real
  database does not touch the API layer.

## Pagination
- Every list endpoint uses the shared envelope `Page[T]` from `app/schemas/pagination.py`
  and takes its parameters from `pagination_params()` / `cursor_pagination_params()` in
  `app/api/pagination.py`. Never redeclare `limit` / `offset` on a route.
- Services accept a `Pagination` object and return `(items, total)`; routes wrap it with
  `Page[Model].of(...)`. Do not slice lists by hand in a service or a route.
- A list that sorts says what by: `pagination_params(sortable=..., default_sort=...)` takes
  `?sort=-created_at,title`, refuses a key outside the list with 422 `unknown_sort_key`,
  and hands the keys to the service in `Pagination.sort`. The service maps each key to a
  column through `ordered()` in `app/db/query.py`, which always adds the id last — without
  that tie-breaker offset pages swap rows between requests. Never an `order_by` built from
  a query string by hand.
- Append-only feeds read newest-first (the audit trail) page by cursor, not offset —
  offset repeats rows as new entries arrive. `cursor_mode` is chosen by the endpoint, not
  by whether the caller sent `before_id`.
