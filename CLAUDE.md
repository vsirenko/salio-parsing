# salio-parsing — Products API

FastAPI service. Deliberately flat: route → service → schema.

## Environment
- Python 3.12+, virtualenv in `.venv`. Run tooling through it: `.venv/bin/pytest`,
  `.venv/bin/ruff`, `.venv/bin/uvicorn`, `.venv/bin/cz`, `.venv/bin/alembic`.
- Install dev deps: `uv pip install -r requirements-dev.txt`.
- Settings come from `.env` via pydantic-settings (`app/core/config.py`).
- PostgreSQL runs in compose on host port **55432**, the api on **8080**. Do not move
  them to 5432 / 8000 — those are taken by other projects on this machine.
- Tests need the `app_test` database and a running `db` container.

## Database
- SQLAlchemy 2.0 async + Alembic. Models in `app/db/models.py`; no repository layer —
  services hold an `AsyncSession` and write queries directly.
- Services call `flush()`, never `commit()`. The request transaction is owned by
  `get_session` and commits when the handler returns.
- Two things deliberately write outside that transaction, through `session_factory`:
  the audit middleware and the sign-in rate limiter. Both record what happened during a
  request that then failed and rolled back, so writing on the request session would roll
  their record back with it. Do not "simplify" either onto the request session, and do
  not add a third without that same reason.
- After changing a model: `alembic revision --autogenerate`, then read the migration
  before committing. `alembic check` must pass.
- `/health` must never touch the database — it is liveness, and a database blip should
  not cause a restart loop. Dependency checks belong in `/health/ready`.

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

## Users and access
- One `User` entity for both panels; `role` (`customer` / `admin`) decides where an account
  may sign in. Do not split into separate admin/customer tables.
- The security boundary is the token audience, not the table. Client tokens carry
  `aud=client`, admin tokens `aud=admin`; each panel decodes with its own expected audience,
  so a token from one is rejected by the other before any role check runs.
- Admin routes go on `admin_router` in `app/api/admin_router.py`, which carries
  `Depends(get_current_admin)` at router level — never guard admin endpoints one by one.
  `admin_public_router` holds only the routes that mint a token without one — login and
  refresh. Anything that takes a token, `/me` included, belongs on `admin_router`.
- Never use `UserInDB` as a `response_model` — it carries `password_hash`. Routes return
  `UserRead`.
- `role` is not accepted from any public input. There is no public registration endpoint;
  accounts are created through `/api/admin/users`.
- Passwords: argon2 via `app/core/security.py`. Never compare or store raw passwords.
- A password never travels through the user update schema. Changing one is its own
  endpoint, and changing your own means proving the current one first.
- Accounts are retired with `is_active = false`, never deleted. The audit trail points at
  the user row and keeps the actor's email denormalised for exactly this reason; there is
  no `DELETE /api/admin/users/{id}` and no service method behind one.
- A user edit must refuse to remove the caller's own admin access (`self_lockout`). That
  one guard is what keeps the panel reachable — the caller is by definition an active
  admin, so whoever else they demote or disable, one is left standing. Do not add a
  "last active admin" count next to it: it can never fire.

## Sessions and revocation
- A JWT carries no server state, so revocation lives on the account: `users.token_epoch`.
  Every token is minted at the account's current epoch and only that epoch is accepted.
- Mint through `_token_pair(user)`, which reads the epoch off the account. Never mint
  from a bare user id — a pair built at the wrong epoch is dead on arrival.
- Bump `token_epoch` from the service whenever access has to end now: password change,
  deactivation. One bump ends every session the account has, refresh tokens included.
- `UserService.get_for_token` is the single place that decides a valid signature is not
  enough. Both the access path in `app/api/deps.py` and the refresh endpoints of both
  panels go through it, so they cannot drift apart. A new reason to reject a token is a
  check inside it, never a check bolted onto one caller.
- The epoch is a counter, not a timestamp. JWT `iat` holds whole seconds, so a
  time-based epoch lets a token minted in the same second survive the change meant to
  kill it.

## Sign-in rate limiting
- Both login endpoints go through `LoginRateLimiter` (`app/services/rate_limit.py`),
  keyed per account and per address. A new endpoint that accepts a password takes the
  limiter with it.
- Counters live in PostgreSQL, not in process memory: several api replicas share one
  budget, otherwise the effective limit is the configured one times the replica count.
- Only credential failures are counted. An attempt made while a bucket is locked is
  refused before the password is checked, so hammering a locked account cannot extend
  its own lock — that is deliberate, not an oversight.
- A successful sign-in clears the account bucket only. Clearing the address bucket as
  well would let anyone holding one valid account wipe the budget for every account
  behind that address.
- Limits come from `settings`, never hard-coded at a call site. Tests read them from
  there too, so tightening a limit does not turn into a test failure.

## Pagination
- Every list endpoint uses the shared envelope `Page[T]` from `app/schemas/pagination.py`
  and takes its parameters from `pagination_params()` / `cursor_pagination_params()` in
  `app/api/pagination.py`. Never redeclare `limit` / `offset` on a route.
- Services accept a `Pagination` object and return `(items, total)`; routes wrap it with
  `Page[Model].of(...)`. Do not slice lists by hand in a service or a route.
- Append-only feeds read newest-first (the audit trail) page by cursor, not offset —
  offset repeats rows as new entries arrive. `cursor_mode` is chosen by the endpoint, not
  by whether the caller sent `before_id`.

## Audit trail
- Every `/api/admin` request is recorded by `AuditMiddleware`. Do not add per-route audit
  calls for the envelope — method, path, status, actor, address and duration are captured
  already.
- The envelope is not the meaning, and the meaning is not optional. Every service method
  behind an admin route that changes state — or refuses to — names what it acted on with
  `audit.set_target(...)` and what it changed with `audit.record_changes(...)` from
  `app/core/audit.py`. An admin action that leaves the trail reading only
  `PATCH /api/admin/users/4 → 409` is not finished.
- Call `set_target` as soon as the row is loaded, before the guards run. A refused
  attempt has to be recorded against the account it was aimed at, not at nothing.
- `record_changes` reports what was actually applied. A refusal applies nothing, so it
  records nothing — the status code already says it failed.
- Sign-in names the actor email before the password is checked. A failed admin sign-in
  is exactly what the trail is read for and it has no actor id to name.
- Never pass raw credentials in. `record_changes` redacts the keys in `SENSITIVE_KEYS`,
  but that is a safety net, not the contract; a new field that can carry a secret is
  added to that set as well.
- Only `open_context` may call `ContextVar.set`. Downstream code mutates the existing
  `AuditContext` object — re-binding the var inside the endpoint task would not propagate
  back to the middleware.
- The trail is append-only. Never add an endpoint or service method that updates or
  deletes an entry.

## Checks
- After any Python change: `.venv/bin/ruff check .` and `.venv/bin/pytest`.
- After any model change: `.venv/bin/alembic check`.
- Before pushing: `.venv/bin/pre-commit run --all-files`.
- Keep `TODO.md` current: tick an item off when it lands, add one when a gap is found.

## Commits
- Conventional Commits, enforced by the commitizen `commit-msg` hook.
- Hooks are installed once per clone: `pre-commit install --install-hooks`.
- `cz bump` derives the version and CHANGELOG from commit history and keeps
  `app_version` in `app/core/config.py` in sync with `[project].version`.

## Config gotchas
- `.env` is gitignored; `.env.example` is the template and must stay in sync.
- Keep `.env.example` comments on their own lines. `docker run --env-file` does not strip
  a trailing `# ...` and would read it as part of the value.
- List-valued settings need `Annotated[list[str], NoDecode]` — pydantic-settings
  JSON-parses list fields from `.env` before field validators run.
