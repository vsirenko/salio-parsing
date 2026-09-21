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
- Reference data belongs in the migration that creates its table, not in a startup seed:
  a `countries` table with no rows is not an empty feature, it is a broken one, and the
  demo seeding is forced off in production. A migration must also stay self-contained —
  it has to keep working against the code of its own day — so it cannot import the rows
  from anywhere, and the test fixture repeats them on purpose.
- Reference tables are keyed by the code the outside world already uses: `EUR`, `LV`. It
  arrives in every feed and appears in every URL, so a surrogate id would add a join to
  almost every query and buy nothing. `login_attempts` is the existing precedent.
- Never seed a fact you are not the source of truth for. A VAT rate or a country's
  currency changes, and a wrong value in reference data is worse than a missing row,
  because it is believed. Such a column is nullable, null means "not known", and an
  explicit null has to be accepted on update — otherwise a wrong value can only ever be
  replaced by another guess, never withdrawn.
- `/health` must never touch the database — it is liveness, and a database blip should
  not cause a restart loop. Dependency checks belong in `/health/ready`.

## Config gotchas
- `.env` is gitignored; `.env.example` is the template and must stay in sync.
- Keep `.env.example` comments on their own lines. `docker run --env-file` does not strip
  a trailing `# ...` and would read it as part of the value.
- List-valued settings need `Annotated[list[str], NoDecode]` — pydantic-settings
  JSON-parses list fields from `.env` before field validators run.
