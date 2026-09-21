# runs

One execution of one channel: starting it, judging it, and deciding what is due.

## Endpoints

| | |
|---|---|
| `GET /api/admin/runs` | what has been collected, newest first, filterable by `source_id` and `status` |
| `GET /api/admin/runs/due` | what the scheduler would start right now |
| `GET /api/admin/runs/{run_id}` | one run, with its coverage and verdict |
| `POST /api/admin/sources/{source_id}/runs` | start one by hand |
| `POST /api/admin/runs/{run_id}/finish` | a worker reporting back |

## How it works

**`runs` is the scheduler's entire memory.** It answers both questions the scheduler has:
when did this channel last run, and is it running now. There is no scheduler state anywhere
else, and deliberately no `next_run_at` column — that would be a cache of `cron + last run`
which goes stale the moment somebody edits a schedule, leaving two sources of truth to
disagree in silence. Seventy channels recomputed on every tick costs nothing.

**Everything the scheduler decides is an ordinary query**, which is why `GET /runs/due`
exists: what the process would start can be read, and asserted, without starting it.

**Two kinds, `full` and `quick`.** A dedicated stock endpoint is not a third — it is another
channel into the same shop whose full pass happens to carry availability and nothing else.

**A slot is read backwards, not projected forwards.** The most recent slot at or before now,
compared against the last start. Projecting forward from the last run means a channel that
has never run, or was off for a week, computes its next slot from a point so far back that
it is permanently outside the catch-up window and never starts at all. A slot missed by more
than six hours is let go rather than caught up: a crawl that late answers a question nobody
is asking, and the next one is along shortly.

## Decisions worth knowing before changing it

- **The contract gates absence, not writes.** A channel that returns three products instead
  of nine hundred has not lied about the three: they are real, and writing them harms
  nothing. The damage is concluding that the eight hundred and ninety-seven unseen ones are
  gone. So only a run that ended `ok` earns the right to treat what it did not see as gone,
  and no staging mechanism is needed to hold a batch until it is judged.
- **A drop is measured from the last run that ended `ok`**, not from the previous run of
  that kind. Against the previous one, two broken crawls in a row pass the second: it fell
  only a little, from an already-wrong number. There is a test that fails if this is changed.
- **The contract only asks about facts the channel claims to deliver.** Checking price
  coverage on a pass that never carries a price would reject every run of it, forever.
- **A worker that broke is not judged on its numbers.** `error` set means `failed` and the
  contract is `not_evaluated`: judging the counts of a crash is judging nothing.
- **A live run is exactly a row without `finished_at`**, tied to the status by a check
  constraint so the two cannot drift, and held to one per channel and kind by a partial
  unique index — by the database, rather than by the hope that only one scheduler exists.
- **`interrupted` is swept at startup, not timed out.** The scheduler is single by
  construction, so anything still running when it starts has no process behind it. The count
  is also an honest metric: it is how often we are being killed.
- **`coverage` is measured; `delivers_*` on the channel is declared.** The gap between them
  is the alarm. A channel whose `gtin` was 0.95 last week and is 0.10 today is a shop that
  changed something, found the day it happens rather than a month later through matching
  quietly getting worse.
- **A malformed cron is refused when it is written**, not skipped at tick time. Skipped, it
  stops that channel in silence: nothing fails, it simply never becomes due, and the first
  symptom is stale prices nobody can explain.

## Not built yet

The scheduler process itself. Everything above is reachable by hand or by a query; nothing
runs on a clock.
