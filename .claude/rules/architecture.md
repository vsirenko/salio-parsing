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
- New resource = `app/schemas/<x>.py` + `app/services/<x>.py` + `app/api/routes/<x>.py`,
  then register the router in `app/api/router.py`.
- Service methods stay `async` even while storage is in-memory, so swapping in a real
  database does not touch the API layer.

## Pagination
- Every list endpoint uses the shared envelope `Page[T]` from `app/schemas/pagination.py`
  and takes its parameters from `pagination_params()` / `cursor_pagination_params()` in
  `app/api/pagination.py`. Never redeclare `limit` / `offset` on a route.
- Services accept a `Pagination` object and return `(items, total)`; routes wrap it with
  `Page[Model].of(...)`. Do not slice lists by hand in a service or a route.
- Append-only feeds read newest-first (the audit trail) page by cursor, not offset —
  offset repeats rows as new entries arrive. `cursor_mode` is chosen by the endpoint, not
  by whether the caller sent `before_id`.
