## Environment
- Python 3.12+, virtualenv in `.venv`. Run tooling through it: `.venv/bin/pytest`,
  `.venv/bin/ruff`, `.venv/bin/uvicorn`, `.venv/bin/cz`, `.venv/bin/alembic`.
- Install dev deps: `uv pip install -r requirements-dev.txt`.
- Settings come from `.env` via pydantic-settings (`app/core/config.py`).
- PostgreSQL runs in compose on host port **55432**, the api on **8080**. Do not move
  them to 5432 / 8000 — those are taken by other projects on this machine.
- Tests need the `app_test` database and a running `db` container.

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
