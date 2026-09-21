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
- The audit middleware is the one exception: it writes through `session_factory` in its
  own transaction, so a record of a failed request survives that request's rollback.
  Do not "simplify" it onto the request session.
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
  subclass, not a new handler.
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
  `admin_public_router` exists only for sign-in; do not add anything else to it.
- Never use `UserInDB` as a `response_model` — it carries `password_hash`. Routes return
  `UserRead`.
- `role` is not accepted from any public input. There is no public registration endpoint;
  accounts are created through `/api/admin/users`.
- Passwords: argon2 via `app/core/security.py`. Never compare or store raw passwords.

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
  calls for the envelope — it is captured already.
- Add meaning from the service layer with `audit.set_target(...)` and
  `audit.record_changes(...)` from `app/core/audit.py`. Never pass raw credentials in;
  `record_changes` redacts known secret keys, but that is a safety net, not the contract.
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
