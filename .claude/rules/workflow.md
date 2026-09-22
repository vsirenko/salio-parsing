## Environment
- Python 3.12+, virtualenv in `.venv`. Run tooling through it: `.venv/bin/pytest`,
  `.venv/bin/ruff`, `.venv/bin/uvicorn`, `.venv/bin/cz`, `.venv/bin/alembic`.
- Install dev deps: `uv pip install -r requirements-dev.txt`.
- Settings come from `.env` via pydantic-settings (`app/core/config.py`).
- PostgreSQL runs in compose on host port **55432**, the api on **8080**. Do not move
  them to 5432 / 8000 — those are taken by other projects on this machine.
- Tests need the `app_test` database and a running `db` container.

## Checks
- After any Python change: `.venv/bin/ruff check .` — always, it takes a second — and the
  tests that cover what changed.
- **Run the tests for what you touched, not the whole suite.** The suite is 513 tests in
  three minutes, and almost all of that is the shared `app_test` database being truncated
  before every one of them: 0.36s per test, where `tests/test_dateks.py` on its own is 4
  seconds. Waiting three minutes to learn that a channel parses a fixture is three minutes
  of nothing. Name the files: `.venv/bin/pytest tests/test_dateks.py`.
- **The whole suite is for changes that reach everybody**: anything in `app/core/`,
  `app/db/`, `app/api/`, `app/schemas/`, `normalization/__init__.py`, `rules.py` or
  `generic.py`, a model or a migration, and before a push. A new feature folder, a new
  channel, a new source ruleset and their tests reach nobody else — their own files are the
  whole of what can break.
- **One test run at a time, and wait for it.** Two runs at once deadlock on the shared
  database: no output, no error, just silence that looks like a slow machine. Never start a
  second before the first has finished. The corollary of running the scoped set is that
  there is nothing to do meanwhile, so do not put it in the background either — the point
  is to read the result.
- After any model change: `.venv/bin/alembic check`.
- Before pushing: `.venv/bin/pre-commit run --all-files`.
- Keep `TODO.md` current: tick an item off when it lands, add one when a gap is found.

## Commits
- Conventional Commits, enforced by the commitizen `commit-msg` hook.
- Hooks are installed once per clone: `pre-commit install --install-hooks`.
- `cz bump` derives the version and CHANGELOG from commit history and keeps
  `app_version` in `app/core/config.py` in sync with `[project].version`.
