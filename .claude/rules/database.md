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

## Config gotchas
- `.env` is gitignored; `.env.example` is the template and must stay in sync.
- Keep `.env.example` comments on their own lines. `docker run --env-file` does not strip
  a trailing `# ...` and would read it as part of the value.
- List-valued settings need `Annotated[list[str], NoDecode]` — pydantic-settings
  JSON-parses list fields from `.env` before field validators run.
