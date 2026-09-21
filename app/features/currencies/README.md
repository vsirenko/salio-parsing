# currencies

ISO 4217, read-only. Reference data everything monetary hangs off.

## Endpoints

`GET /api/admin/currencies` — the list. There is no create: a new currency arrives with a
migration, not a POST.

## How it works

Keyed by the ISO code rather than a surrogate id. The code arrives in every feed and appears
in every URL, so an id would add a join to almost every query and buy nothing. That is the
rule for reference data whose code comes from outside and does not change; where the
identifier is ours and editable — a slug — the row keeps a stable key instead.

`minor_units` is the field that earns its place. It is what says `Numeric(12, 2)` is the
right shape, and the only thing that would catch a second currency with different precision.
While EUR is the only row it looks pointless; the day it is not, it is what stops cents
being silently lost.

## Decisions worth knowing before changing it

- Seeded in the migration that creates the table, not by a startup seed: the demo seeding is
  forced off in production, and an empty currencies table is not an empty feature but a
  broken one.
- The currency of a price is stored on `price_event` as well, not only derived from the
  market. A recorded price has to say what it was in, or editing one reference row
  retroactively rewrites the meaning of the whole history.

See also `.claude/rules/database.md`.
