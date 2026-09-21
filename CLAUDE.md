# salio-parsing — Products API

FastAPI service. Deliberately flat: route → service → schema.

## Environment
- Python 3.12+, virtualenv in `.venv`. Run tooling through it: `.venv/bin/pytest`,
  `.venv/bin/ruff`, `.venv/bin/uvicorn`, `.venv/bin/cz`.
- Install dev deps: `uv pip install -r requirements-dev.txt`.
- Settings come from `.env` via pydantic-settings (`app/core/config.py`).

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

## Checks
- After any Python change: `.venv/bin/ruff check .` and `.venv/bin/pytest`.
- Before pushing: `.venv/bin/pre-commit run --all-files`.

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
