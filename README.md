# salio-parsing

FastAPI service on PostgreSQL: authentication with two separate panels, an append-only
audit trail, and shared pagination. Underneath it, the reference data and taxonomy of a
price parser that is being built — see [docs/parser-design.md](docs/parser-design.md).

Deliberately flat: route → service → schema. No repository pattern, no CQRS, no event bus.
The tree is sliced by feature rather than by layer — everything one feature needs sits in
`app/features/<name>/`.

The repository is named for a price parser that is **not built yet**. Its shape, and the
questions that have to be answered against real data first, are written down in
[docs/parser-design.md](docs/parser-design.md). What exists of it so far is the reference
data underneath: currencies, countries and markets.

## Requirements

- Python 3.12+
- Docker (PostgreSQL runs in compose)

See [TODO.md](TODO.md) for what is not built yet.

## Project structure

```
app/
├── main.py                  # app factory: CORS, routers, error handlers, lifespan
├── api/                     # wiring only — no routes of its own
│   ├── deps.py              # shared dependencies, auth guards, service factories
│   ├── pagination.py        # limit / offset / before_id query dependencies
│   ├── router.py            # client routes -> /api/*
│   └── admin_router.py      # admin routes  -> /api/admin/*, guarded at router level
├── core/                    # cross-cutting, and knows nothing about any feature
│   ├── config.py            # Settings (pydantic-settings, reads .env)
│   ├── security.py          # argon2, JWT minting and verification, token vocabulary
│   ├── exceptions.py        # AppError and its subclasses
│   ├── error_handlers.py    # one consistent error body for every failure
│   ├── audit.py             # per-request audit context + redaction
│   ├── net.py               # the caller's address, shared by audit and rate limiting
│   └── logging.py
├── db/
│   ├── base.py              # DeclarativeBase + constraint naming convention
│   ├── models.py            # every table: User, Product, AuditEntry, LoginAttempt,
│   │                        # Currency, Country, Market
│   ├── query.py             # count + window helper shared by the services
│   └── session.py           # engine, request session, independent session factory
├── schemas/                 # only what every feature shares
│   ├── common.py            # ErrorResponse, HealthResponse
│   └── pagination.py        # Page[T] envelope + Pagination value object
└── features/
    ├── users/               # accounts and sessions, both panels
    │   ├── router.py        # /api/auth/*
    │   ├── admin_router.py  # /api/admin/auth/*, /api/admin/users/*
    │   ├── service.py
    │   └── schemas.py
    ├── brands/              # /api/admin/brands
    ├── audit/               # middleware + /api/admin/audit, read-only
    ├── currencies/          # /api/admin/currencies, read-only reference data
    ├── countries/           # /api/admin/countries
    ├── markets/             # /api/admin/markets — the storefronts we run
    ├── rate_limit/          # sign-in limiter; no router, nothing exposes it
    └── health/              # /health, /health/ready; no service, it has no state
alembic/                     # migrations
docs/parser-design.md        # the parser: shape, decisions, open questions
tools/preview.py             # read-only: writes two HTML pages to look at the result
tests/                       # test_architecture.py enforces the import direction
.pre-commit-config.yaml      # ruff + commit message linting
```

Imports point one way: `features` may import `core`, `db` and `schemas`; those three never
import a feature. `tests/test_architecture.py` fails on a violation.

## Setup

```bash
# 1. PostgreSQL. Host ports are 55432 (db) and 8080 (api) — 5432 and 8000 are
#    commonly taken by other projects.
docker compose up -d db

# 2. Application
python3.12 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt          # runtime only
pip install -r requirements-dev.txt      # + pytest, httpx, ruff

cp .env.example .env

# 3. Schema
alembic upgrade head
```

With [uv](https://docs.astral.sh/uv/) instead:

```bash
uv venv --python 3.12
uv pip install -r requirements-dev.txt
cp .env.example .env
```

## Run

```bash
# development — auto-reload
uvicorn app.main:app --reload --port 8000

# production — several worker processes
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Demo accounts are created on startup while `SEED_USERS=true`.

- Swagger UI: http://localhost:8080/docs
- ReDoc: http://localhost:8080/redoc
- OpenAPI JSON: http://localhost:8080/openapi.json

Set `DOCS_ENABLED=false` in production to hide all three.

## Database

PostgreSQL via SQLAlchemy 2.0 (async, asyncpg) with Alembic migrations. No repository
layer: a service takes an `AsyncSession` and writes queries directly.

```bash
alembic upgrade head                      # apply migrations
alembic revision --autogenerate -m "..."  # after changing app/db/models.py
alembic check                             # fails if models and migrations disagree
alembic downgrade -1                      # step back one
```

Transactions:

- `get_session` gives one transaction per request — committed when the handler returns,
  rolled back if it raises. A service calls `flush()`, never `commit()`.
- Two things deliberately write outside it, through `session_factory`: the audit
  middleware and the sign-in rate limiter. Both record what happened during a request
  that then failed and rolled back, so a record on the request session would roll back
  with it.
- `DB_USE_NULL_POOL=true` stops connections being pooled, for tests (each client runs
  its own event loop and an asyncpg connection cannot cross loops) and for serverless.

Two probes, deliberately different: `/health` is liveness and touches nothing, so a
database blip does not turn into a restart loop; `/health/ready` runs `select 1` and
answers 503 when the database is down, which is what should pull the instance out of
the load balancer.

## Looking at the result

The API serves JSON and there is no panel yet, so the only way to see whether the catalogue
is any good is to build the pages and look:

```bash
.venv/bin/python -m tools.preview
open var/preview/index.html
```

It reads the database, writes two self-contained files under `var/preview/` and stops.
Nothing is served and nothing is cached — running it again is the whole refresh story.

- `index.html` — the storefront: products, their variants, and every shop's price for each.
- `unmatched.html` — the listings the matcher could not place, grouped by what is missing,
  because "386 did not match" is a number nobody can act on. The grouping mirrors the order
  `MatchingService.promote_queue` checks things in, so a listing is filed under the first
  thing that stops it.

## Tests & lint

Tests run against a real PostgreSQL — the schema uses JSONB, arrays and a functional
unique index, so SQLite would be testing something we do not ship. Create the test
database once:

```bash
docker compose exec db psql -U app -c "create database app_test owner app;"
```

```bash
pytest
ruff check .
ruff format .
alembic check
```

Each test truncates and re-seeds rather than rolling back a shared transaction, because
the audit middleware writes in its own transaction and a rollback-based fixture would
hide it.

## Git hooks & commit messages

Run once after cloning:

```bash
pre-commit install --install-hooks
```

That wires up two stages:

- **pre-commit** — `ruff check --fix`, `ruff format`, plus basic file hygiene.
- **commit-msg** — [commitizen](https://commitizen-tools.github.io/commitizen/) enforces
  [Conventional Commits](https://www.conventionalcommits.org/).

Message format:

```
<type>(<optional scope>): <description>

[optional body]
[optional footer]
```

Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`,
`chore`, `revert`. Append `!` (`feat!:`) or a `BREAKING CHANGE:` footer for breaking changes.

```bash
git commit -m "feat(api): add product search filter"   # ok
git commit -m "fix: return 409 on duplicate name"      # ok
git commit -m "updated stuff"                          # rejected by the hook
```

Helpers:

```bash
cz commit            # interactive prompt that builds a valid message
cz check --rev-range HEAD~5..HEAD   # lint existing commits
cz bump              # bump version + CHANGELOG from commit history, then tag
pre-commit run --all-files
```

`cz bump` reads the version from `[project].version` and keeps `app_version` in
`app/core/config.py` in sync.

## Docker

```bash
docker compose up -d --build     # db + migrations + api on http://localhost:8080
docker compose logs -f api
docker compose down              # add -v to drop the data volume
```

Compose runs three services: `db`, a one-shot `migrate` that applies `alembic upgrade
head` and exits, and `api`, which starts only once the migration has succeeded. Keeping
migrations out of the api start command means several replicas cannot race applying the
same migration.

The image runs as a non-root user and ships a `HEALTHCHECK` hitting `/health`.

## Configuration

Every variable is read from the environment or `.env` (see `.env.example`).

| Variable | Default | Description |
| --- | --- | --- |
| `APP_NAME` | `salio-parsing` | Title shown in Swagger |
| `APP_VERSION` | `0.1.0` | API version |
| `ENVIRONMENT` | `local` | `local` / `dev` / `staging` / `production` |
| `DEBUG` | `false` | FastAPI debug mode |
| `LOG_LEVEL` | `INFO` | Root log level |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Bind address |
| `API_PREFIX` | `/api` | Prefix for business routes |
| `DOCS_ENABLED` | `true` | Expose `/docs`, `/redoc`, `/openapi.json` |
| `SECRET_KEY` | dev placeholder | JWT signing key, min 32 chars; must be changed in production |
| `JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `ACCESS_TOKEN_TTL_MINUTES` | `15` | Access token lifetime |
| `REFRESH_TOKEN_TTL_DAYS` | `30` | Refresh token lifetime |
| `SEED_USERS` | `true` | Create demo accounts; must be `false` in production |
| `TRUST_PROXY_HEADERS` | `false` | Read `X-Forwarded-For` / `X-Request-ID`; only enable behind a trusted proxy |
| `DATABASE_URL` | local compose | `postgresql+asyncpg://…` |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `5` / `10` | Connection pool |
| `DB_ECHO` | `false` | Log every SQL statement |
| `DB_USE_NULL_POOL` | `false` | Do not pool connections (tests, serverless) |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `CORS_ALLOW_CREDENTIALS` | `true` | Send `Access-Control-Allow-Credentials` |

Use explicit origins whenever `CORS_ALLOW_CREDENTIALS=true` — browsers reject `*` with credentials.

## Endpoints

Two audiences share one `User` entity but are separated at the token level: a JWT minted
for one panel carries an `aud` claim the other panel rejects.

**Public**

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | Liveness probe, no dependencies |
| GET | `/health/ready` | Readiness probe, checks the database |
| POST | `/api/auth/login` | Customer sign-in, returns access + refresh |
| POST | `/api/auth/refresh` | Exchange a refresh token for a new pair |
| POST | `/api/admin/auth/login` | Admin sign-in |
| POST | `/api/admin/auth/refresh` | Refresh the admin session |

Both sign-in endpoints are rate limited per account and per address.

**Client token required** (`aud=client`)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/auth/me` | Current customer |
| POST | `/api/auth/password` | Change your own password, returns a fresh pair |

**Admin token required** (`aud=admin`)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/admin/auth/me` | Current admin |
| POST | `/api/admin/auth/password` | Change your own password, returns a fresh pair |
| GET | `/api/admin/users` | List users (`limit`, `offset`, `role`) |
| POST | `/api/admin/users` | Create a user |
| GET | `/api/admin/users/{id}` | Get one user |
| PATCH | `/api/admin/users/{id}` | Edit name, role, active flag |
| GET | `/api/admin/audit` | Read the audit trail (cursor paging) |
| GET | `/api/admin/currencies` | ISO 4217, read-only |
| GET | `/api/admin/countries` | List countries (`is_eu`) |
| POST | `/api/admin/countries` | Add a country |
| GET · PATCH | `/api/admin/countries/{code}` | Read or edit one — mainly its VAT rate |
| GET | `/api/admin/markets` | List markets (`is_enabled`) |
| POST | `/api/admin/markets` | Open a market |
| GET · PATCH | `/api/admin/markets/{code}` | Read or edit one — mainly `is_enabled` |

| GET · POST | `/api/admin/brands` | List and create brands |
| GET | `/api/admin/brands/resolve` | What a string resolves to (`q`, `titles_only`) |
| GET · PATCH | `/api/admin/brands/{brand_id}` | Read or edit one |
| GET · POST | `/api/admin/categories` | The category tree |
| GET · PATCH | `/api/admin/categories/{category_id}` | Read or edit one |
| GET · POST | `/api/admin/attributes` | The canonical attribute registry |

> There is **no public read API yet.** Everything above `/api/auth` is admin-only, so the
> customer panel can sign in and change its password and nothing else. The storefront is
> not built.

### Access model

- One `User` row per account; `role` (`customer` / `admin`) decides which panel it may
  sign in to. Signing in at the wrong panel fails with `wrong_panel`.
- `app/api/admin_router.py` carries `Depends(get_current_admin)` on the router itself, so
  every admin route is protected by default and a new one cannot forget the guard.
  `admin_public_router` is the single named exception, and holds only sign-in.
- Access tokens live 15 minutes, refresh tokens 30 days. A refresh token is rejected where
  an access token is expected (`type` claim).
- Tokens carry no server state, so revocation lives on the account: `users.token_epoch`.
  Every token is minted at the account's current epoch and only that epoch is accepted, so
  a password change or a deactivation ends every session at once. It is a counter rather
  than a timestamp because JWT `iat` holds whole seconds, and a token minted in the same
  second would survive a time comparison.
- `UserService.get_for_token` is the single place that decides a valid signature is not
  enough. Both the access path and the refresh endpoints go through it.
- Failed sign-ins are counted in PostgreSQL per account and per address. Crossing a limit
  locks that bucket, and the lock doubles with each further failure. The counters are
  written outside the request transaction, or a rolled-back failure would not count.
- Passwords are hashed with argon2. `UserRead` has no hash on it, so a handler cannot leak
  one by accident.
- There is no public registration endpoint. Accounts are created via `/api/admin/users`.

> Sessions can only be ended all at once. There is no list of active sessions and no way
> to sign out one device — that needs a `refresh_tokens` table with `jti`, rotation and
> reuse detection.

### Pagination

Every list endpoint returns the same envelope and takes its paging parameters from a
shared dependency in `app/api/pagination.py`, so bounds and defaults are declared once.

```json
{ "items": [], "total": 42, "limit": 20, "offset": 0, "next_cursor": null, "has_more": true }
```

Two modes, one shape:

| Mode | Parameters | Used by | Why |
| --- | --- | --- | --- |
| offset | `limit`, `offset` | users, countries, brands | Stable collections paged by position |
| cursor | `limit`, `before_id` | audit | Append-only feed read newest-first |

Offset paging drifts on an append-only feed: entries written between two requests push
everything down, so page 2 repeats rows page 1 already showed. Cursor paging anchors to
an id instead — follow `next_cursor` until it comes back `null`.

```python
PageParams = Annotated[Pagination, Depends(pagination_params())]  # 1..100, default 20
PageParams = Annotated[Pagination, Depends(cursor_pagination_params(max_limit=200))]  # cursor mode
```

A service takes the `Pagination` object and returns `(items, total)`; the route wraps it
with `Page[Model].of(items, total, pagination)`. Nothing slices lists by hand.

> In cursor mode `before_id` is applied as a filter, so `total` reports what remains from
> the anchor rather than the size of the whole feed. That is what makes the walk terminate
> exactly, with no trailing empty page.

### Audit trail

Every request under `/api/admin` produces one audit record, including reads, rejected
requests and failed sign-ins. This is a business record, not an application log: it is
queryable and append-only, and lives in its own store.

- `AuditMiddleware` writes the envelope — actor, method, path, status, outcome, client IP,
  user agent, duration, request id. Middleware rather than a dependency, so a new admin
  route cannot silently escape the trail and so the final status code is known.
- The service layer adds meaning through `app/core/audit.py`: `set_target("user", id)` and
  `record_changes(...)`. Services have no request object, so the context travels in a
  ContextVar.
- `set_target` is called as soon as the row is loaded, before the guards run, so a refused
  attempt is recorded against what it was aimed at rather than at nothing. `record_changes`
  reports only what was actually applied — a refusal applies nothing.
- Everything handed to `record_changes` has to be JSON-safe (`model_dump(mode="json")`).
  The column is JSONB and a `Decimal` makes the write fail.
- `record_changes` redacts anything that looks like a credential (`password`, `token`,
  `secret`, `api_key`, …), recursing into nested structures. Callers are expected to pass
  clean data; this is the second line of defence.
- Failed sign-ins are recorded with the attempted email and no actor id.
- Each response carries `X-Request-ID`, matching `request_id` on the record, so an entry
  can be tied back to the application logs.
- `GET /api/admin/audit` supports `actor_id`, `method`, `path`, `outcome`, `since`,
  `until`, `limit`, `offset`, newest first. There is no write, update or delete endpoint.

Client traffic is not audited — the middleware is scoped by path prefix. Widen the prefix
in `app/main.py` when that changes.

> A failed audit write is logged and swallowed rather than failing the request, which has
> already hidden a bug once: a `Decimal` reaching the JSONB column made the write fail, and
> the endpoint returned 200 with no record of what it had done. If the trail ever becomes a
> compliance requirement, invert that in `AuditMiddleware` so the action fails when it
> cannot be recorded.

### Demo accounts

Created on startup while `SEED_USERS=true`; startup fails if that is still true in production.

| Email | Password | Role |
| --- | --- | --- |
| `admin@example.com` | `admin-password` | admin |
| `customer@example.com` | `customer-password` | customer |

### Errors

Every non-2xx response has the same shape:

```json
{
  "error": {
    "code": "not_found",
    "message": "Product 9999 not found",
    "details": null
  }
}
```

`validation_error` (422) fills `details` with a per-field list. Unhandled exceptions are logged
with a traceback and returned as a generic 500 — internals never leak to the client.

## curl examples

```bash
# health
curl http://localhost:8080/health

# readiness — checks the database
curl http://localhost:8080/health/ready
```

### Auth

```bash
# customer sign-in
TOKEN=$(curl -s -X POST http://localhost:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "customer@example.com", "password": "customer-password"}' \
  | python -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

curl http://localhost:8080/api/auth/me -H "Authorization: Bearer $TOKEN"

# admin sign-in (separate endpoint, separate audience)
ADMIN=$(curl -s -X POST http://localhost:8080/api/admin/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "admin-password"}' \
  | python -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

curl http://localhost:8080/api/admin/users -H "Authorization: Bearer $ADMIN"

# create a user from the admin panel
curl -X POST http://localhost:8080/api/admin/users \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"email": "new@example.com", "password": "password123", "role": "customer"}'

# a client token is rejected by the admin API
curl -i http://localhost:8080/api/admin/users -H "Authorization: Bearer $TOKEN"
```

### Audit trail

```bash
# everything the admins did, newest first
curl "http://localhost:8080/api/admin/audit?limit=20" -H "Authorization: Bearer $ADMIN"

# only what failed (rejected requests, bad sign-ins)
curl "http://localhost:8080/api/admin/audit?outcome=failure" -H "Authorization: Bearer $ADMIN"

# one admin, writes only, since a point in time
curl "http://localhost:8080/api/admin/audit?actor_id=1&method=POST&since=2026-01-01T00:00:00Z" \
  -H "Authorization: Bearer $ADMIN"

# walk the trail: follow next_cursor until it comes back null
curl "http://localhost:8080/api/admin/audit?limit=50&before_id=120" -H "Authorization: Bearer $ADMIN"
```

## Extending

- **Feature documentation** — every folder under `app/features/` holds a `README.md`, and
  changing the feature means changing it in the same commit. `tests/test_architecture.py`
  checks that one exists and that its endpoint table matches the live routes.
- **New resource** — add `app/features/<thing>/` holding `schemas.py`, `service.py` and
  `router.py` (plus `admin_router.py` if the admin panel touches it), then mount it in
  `app/api/router.py` or `app/api/admin_router.py`. Mount it nowhere else.
- **Schema change** — edit `app/db/models.py` (every model lives there, whichever feature
  owns it), run `alembic revision --autogenerate`, read the generated migration before
  committing it.
- **Reference data** — goes in the migration that creates its table, not a startup seed.
  The demo seeding is forced off in production, and an empty lookup table is a broken
  feature rather than an empty one.
- **New error type** — subclass `AppError` in `app/core/exceptions.py`; it is serialized
  automatically, no handler to write.
