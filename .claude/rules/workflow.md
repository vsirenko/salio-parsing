## Environment
- Python 3.12+, virtualenv in `.venv`. Run tooling through it: `.venv/bin/pytest`,
  `.venv/bin/ruff`, `.venv/bin/uvicorn`, `.venv/bin/cz`, `.venv/bin/alembic`.
- Install dev deps at the locked versions: `uv pip sync requirements-dev.lock`. The image
  installs `requirements.lock` and CI `requirements-dev.lock`, so all three run the same
  versions. `requirements*.txt` hold the ranges; after changing one, recompile both locks —
  `uv pip compile requirements.txt -o requirements.lock --python-version 3.12 --no-header`,
  then `uv pip compile requirements-dev.txt -c requirements.lock -o requirements-dev.lock
  --python-version 3.12 --no-header` — and commit them with it.
- Settings come from `.env` via pydantic-settings (`app/core/config.py`).
- PostgreSQL runs in compose on host port **55432**, the api on **8080**. Do not move
  them to 5432 / 8000 — those are taken by other projects on this machine.
- Tests need the `app_test` database and a running `db` container.

## Checks
- After any Python change: `.venv/bin/ruff check .` — always, it takes a second — and the
  tests that cover what changed.
- **The whole suite takes about fifteen seconds** — 839 tests on eight workers, each on a
  database of its own (`app_test_gw0` …), which `.venv/bin/pytest` does by default. Run it
  after any change that reaches beyond one feature, and before a push; for a change inside
  one feature folder or channel, its own files are enough and quicker still
  (`.venv/bin/pytest tests/test_dateks.py`). It used to take five minutes, and what made
  it slow is worth knowing before adding a fixture: a new database connection per request
  (16 ms, against 0.3 ms for a query on an open one), argon2 at full cost on every sign-in,
  and a `TRUNCATE` of every table before every test. `tests/conftest.py` says how each is
  avoided — keep the requests on the session's event loop, and do not open a loop of your
  own in a test (`event_loop.run_until_complete(...)` instead).
- **One test run at a time, and wait for it.** Two runs share the same worker databases and
  empty them under each other: no output, no error, just silence that looks like a slow
  machine. It is fifteen seconds; there is nothing to do meanwhile, so do not put it in the
  background either — the point is to read the result.
- After any model change: `.venv/bin/alembic check`.
- Before pushing: `.venv/bin/pre-commit run --all-files`.
- Keep `TODO.md` current: tick an item off when it lands, add one when a gap is found.

## Commits
- Conventional Commits, enforced by the commitizen `commit-msg` hook.
- Hooks are installed once per clone: `pre-commit install --install-hooks`.
- `cz bump` derives the version and CHANGELOG from commit history and keeps
  `app_version` in `app/core/config.py` in sync with `[project].version`.
