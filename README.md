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
│   ├── deps.py             # shared FastAPI dependencies
│   ├── router.py           # aggregates every /api route
│   └── routes/
│       ├── health.py       # GET /health
│       └── products.py     # GET/POST /api/products
├── core/
│   ├── config.py           # Settings (pydantic-settings, reads .env)
│   ├── error_handlers.py   # one consistent error body for every failure
│   ├── exceptions.py       # AppError / NotFoundError / ConflictError
│   └── logging.py
├── schemas/
│   ├── common.py           # ErrorResponse, Page[T], HealthResponse
│   └── product.py          # ProductCreate / ProductRead
└── services/
    └── products.py         # business logic + in-memory storage
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
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `CORS_ALLOW_CREDENTIALS` | `true` | Send `Access-Control-Allow-Credentials` |

Use explicit origins whenever `CORS_ALLOW_CREDENTIALS=true` — browsers reject `*` with credentials.

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | Liveness probe |
| GET | `/api/products` | List products (`limit`, `offset`, `search`, `in_stock`) |
| POST | `/api/products` | Create a product |
| GET | `/api/products/{id}` | Get one product |

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

## Extending

- **New resource** — add `app/schemas/<thing>.py`, `app/services/<thing>.py`,
  `app/api/routes/<thing>.py`, then register the router in `app/api/router.py`.
- **Real database** — replace the dict inside `ProductService` with DB calls. Routes and schemas
  don't change; they only know schemas and domain exceptions.
- **New error type** — subclass `AppError` in `app/core/exceptions.py`; it is serialized
  automatically, no handler to write.
