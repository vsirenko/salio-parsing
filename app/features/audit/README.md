# audit

An append-only record of every admin action. A business record, not an application log:
queryable, and written even when the request it describes failed.

## Endpoints

`GET /api/admin/audit` — read the trail, newest first, by cursor. There is no write, update
or delete endpoint, and there must never be one.

## How it works

**`middleware.py` writes the envelope** — actor, method, path, status, address, user agent,
duration, request id — for every request under `/api/admin`. Middleware rather than a
dependency for two reasons: a dependency cannot see the status code the handler ended up
returning, and middleware cannot be forgotten when somebody adds a route.

**It writes through `session_factory`, in its own transaction.** A record of a failed
request must survive that request's rollback.

**Services add the meaning** through `app/core/audit.py`: `set_target(...)` and
`record_changes(...)`. Services have no request object, so the context travels in a
ContextVar. Only `open_context` ever calls `.set()` — downstream code mutates the existing
object, because re-binding the var inside the endpoint task would not propagate back to the
middleware.

**Reading is cursor-paged, not offset-paged.** Entries written between two requests push
everything down a page, so offset would repeat rows on an append-only feed.

## Decisions worth knowing before changing it

- `set_target` is called as soon as the row is loaded, *before* the guards, so a refused
  attempt is recorded against what it was aimed at rather than at nothing.
- `record_changes` reports only what was applied. A refusal applies nothing; the status code
  already says it failed.
- Everything handed to `record_changes` must be JSON-safe — `model_dump(mode="json")`. The
  column is JSONB and a `Decimal` makes the write fail, which the middleware swallows: the
  only symptom is an action that returned 200 and left no record. This has happened once.
- A failed write is logged and swallowed rather than failing the request. If the trail
  becomes a compliance requirement, invert that here.
- Client traffic is not audited; the middleware is scoped by path prefix in `app/main.py`.

See also `.claude/rules/audit.md`.
