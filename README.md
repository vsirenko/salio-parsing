# Products API

Production-ready FastAPI service: Pydantic schemas, `.env` config, unified error handling,
CORS, auto-generated Swagger/OpenAPI, and a Docker image.

Deliberately flat: routes → service → schemas. No repository pattern, no CQRS, no event bus.

## Requirements

- Python 3.12+
- (optional) Docker

## Project structure

```
app/
├── main.py                 # app factory: CORS, routers, error handlers, lifespan
├── api/
│   ├── deps.py             # shared deps + auth guards
│   ├── router.py           # client routes    -> /api/*
│   ├── admin_router.py     # admin routes     -> /api/admin/*, guarded at router level
│   └── routes/
│       ├── health.py       # GET /health
│       ├── auth.py         # client sign-in
│       ├── products.py     # GET/POST /api/products
│       └── admin/
│           ├── auth.py     # admin sign-in
│           └── users.py    # admin user management
├── core/
│   ├── config.py           # Settings (pydantic-settings, reads .env)
│   ├── error_handlers.py   # one consistent error body for every failure
│   ├── exceptions.py       # AppError / NotFoundError / ConflictError
│   ├── security.py         # argon2 hashing, JWT minting and verification
│   └── logging.py
├── schemas/
│   ├── common.py           # ErrorResponse, Page[T], HealthResponse
│   ├── auth.py             # Audience, TokenPair, LoginRequest
│   ├── user.py             # Role, UserCreate / UserRead / UserInDB
│   └── product.py          # ProductCreate / ProductRead
└── services/
    ├── products.py         # business logic + in-memory storage
    └── users.py            # lookup, authentication, panel check
tests/
.pre-commit-config.yaml     # ruff + commit message linting
```

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt          # runtime only
pip install -r requirements-dev.txt      # + pytest, httpx, ruff

cp .env.example .env
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

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI JSON: http://localhost:8000/openapi.json

Set `DOCS_ENABLED=false` in production to hide all three.

## Tests & lint

```bash
pytest
ruff check .
ruff format .
```

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
docker build -t products-api .
docker run --rm -p 8000:8000 --env-file .env products-api
```

The image runs as a non-root user and ships a `HEALTHCHECK` hitting `/health`.

## Configuration

Every variable is read from the environment or `.env` (see `.env.example`).

| Variable | Default | Description |
| --- | --- | --- |
| `APP_NAME` | `Products API` | Title shown in Swagger |
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
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `CORS_ALLOW_CREDENTIALS` | `true` | Send `Access-Control-Allow-Credentials` |

Use explicit origins whenever `CORS_ALLOW_CREDENTIALS=true` — browsers reject `*` with credentials.

## Endpoints

Two audiences share one `User` entity but are separated at the token level: a JWT minted
for one panel carries an `aud` claim the other panel rejects.

**Public**

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | Liveness probe |
| POST | `/api/auth/login` | Customer sign-in, returns access + refresh |
| POST | `/api/auth/refresh` | Exchange a refresh token for a new pair |
| POST | `/api/admin/auth/login` | Admin sign-in |
| POST | `/api/admin/auth/refresh` | Refresh the admin session |

**Client token required** (`aud=client`)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/auth/me` | Current customer |

**Admin token required** (`aud=admin`)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/admin/auth/me` | Current admin |
| GET | `/api/admin/users` | List users (`limit`, `offset`, `role`) |
| POST | `/api/admin/users` | Create a user |
| GET | `/api/admin/users/{id}` | Get one user |

**Open for now** (products are not behind auth yet)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/products` | List products (`limit`, `offset`, `search`, `in_stock`) |
| POST | `/api/products` | Create a product |
| GET | `/api/products/{id}` | Get one product |

### Access model

- One `User` row per account; `role` (`customer` / `admin`) decides which panel it may
  sign in to. Signing in at the wrong panel fails with `wrong_panel`.
- `app/api/admin_router.py` carries `Depends(get_current_admin)` on the router itself, so
  every admin route is protected by default and a new one cannot forget the guard.
  `admin_public_router` is the single named exception, and holds only sign-in.
- Access tokens live 15 minutes, refresh tokens 30 days. A refresh token is rejected where
  an access token is expected (`type` claim).
- Passwords are hashed with argon2. `UserRead` has no hash on it, so a handler cannot leak
  one by accident.
- There is no public registration endpoint. Accounts are created via `/api/admin/users`.

> Refresh tokens are stateless, so signing out everywhere is not possible yet. Add a `jti`
> denylist (Redis) or rotation when that is needed.

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
curl http://localhost:8000/health

# list
curl "http://localhost:8000/api/products?limit=2&offset=0"

# list + filters
curl "http://localhost:8000/api/products?search=coffee&in_stock=true"

# create
curl -X POST http://localhost:8000/api/products \
  -H "Content-Type: application/json" \
  -d '{
        "name": "Grinder",
        "description": "Flat burr",
        "price": 129.90,
        "currency": "EUR",
        "in_stock": true,
        "tags": ["coffee"]
      }'

# one product
curl http://localhost:8000/api/products/1

# 404
curl -i http://localhost:8000/api/products/9999

# 422
curl -i -X POST http://localhost:8000/api/products \
  -H "Content-Type: application/json" \
  -d '{"name": "", "price": -5}'
```

### Auth

```bash
# customer sign-in
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "customer@example.com", "password": "customer-password"}' \
  | python -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

curl http://localhost:8000/api/auth/me -H "Authorization: Bearer $TOKEN"

# admin sign-in (separate endpoint, separate audience)
ADMIN=$(curl -s -X POST http://localhost:8000/api/admin/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "admin-password"}' \
  | python -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

curl http://localhost:8000/api/admin/users -H "Authorization: Bearer $ADMIN"

# create a user from the admin panel
curl -X POST http://localhost:8000/api/admin/users \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"email": "new@example.com", "password": "password123", "role": "customer"}'

# a client token is rejected by the admin API
curl -i http://localhost:8000/api/admin/users -H "Authorization: Bearer $TOKEN"
```

## Extending

- **New resource** — add `app/schemas/<thing>.py`, `app/services/<thing>.py`,
  `app/api/routes/<thing>.py`, then register the router in `app/api/router.py`.
- **Real database** — replace the dict inside `ProductService` with DB calls. Routes and schemas
  don't change; they only know schemas and domain exceptions.
- **New error type** — subclass `AppError` in `app/core/exceptions.py`; it is serialized
  automatically, no handler to write.
