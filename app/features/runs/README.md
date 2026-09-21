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

## The scheduler

```bash
python -m app.features.runs.scheduler          # the daemon; compose runs this
python -m app.features.runs.scheduler --once   # one tick and exit
```

Its own process rather than a thread inside the API, where it would be started once per
uvicorn worker and die with whichever one held it. Being the only one is a Postgres
advisory lock taken on a connection of its own — a pooled connection would be recycled and
take the lock with it, which is the quiet version of running two schedulers. A second copy
exits immediately, so scaling the service by accident costs nothing.

```
start   take the lock, or exit
        sweep: anything still running has no process behind it

tick    reap finished workers
        ask due(), start what there is room for, spawn one process per run

stop    wait for what is running, then reap so each one keeps its own verdict
```

**One process per run**, so a parser that leaks or wedges takes down its own process and
nothing else. `RUN_TIMEOUT_MINUTES` kills one that stopped answering; without it a hung
channel would hold its own live-run slot forever.

**The scheduler finishes a run its worker did not**, because it is the only thing that knows
the worker is gone. It never overwrites one that reported for itself: the attempt conflicts
and is dropped, so the worker's own reason survives — which is also why shutdown reaps
rather than closing everything as "scheduler stopped".

**`SCHEDULER_MAX_RUNNING` defaults to 1.** Two concurrent crawls on a small box is how the
memory limit gets found, and a channel collects far faster with a couple of neighbours than
with a dozen.

## The worker

One process per run, spawned by the scheduler, so a parser that leaks or wedges takes down
its own process and nothing else.

**It reaches the service over HTTP with its own credentials, not through the database.** A
parser is the one thing here that runs hostile input through itself all day, and what it
holds while doing that decides what a compromised one is worth. A worker token carries
`aud=worker` and reaches exactly five routes:

| | |
|---|---|
| `POST /api/worker/auth/login` · `POST /api/worker/auth/refresh` | its own session |
| `GET /api/worker/runs/{run_id}` | the job |
| `POST /api/worker/runs/{run_id}/finish` | report back |
| `POST /api/worker/sources/{source_id}/offers/batch` | hand over a pass |

`tests/test_worker.py` asserts that exact set, so a sixth route is a decision rather than
an accident.

**The job is asked for, not passed on the command line.** The channel's declaration travels
with the run — including which facts *this* pass is expected to bring back, already chosen
by the kind so a worker cannot pick the wrong list — which means a worker started by hand
gets the same answer as one the scheduler spawned.

**A handed-over pass writes no audit entry**, unlike the same call on the admin router. Not
an oversight: the trail records what an administrator did, and a scheduled crawl is not
that. What a run collected is recorded on the run, which is where somebody would look.

**A 401 mid-pass is retried once** through a fresh sign-in. A slow channel can outlive an
access token, and losing a completed crawl to an expiry would be absurd.

## Not built yet

**No channel is implemented.** `worker.py` has an empty registry, so every run ends as a
failure naming the channel it could not collect. That is the honest state: the machinery
around collecting is built and the collecting is not. Adding a channel is adding an entry to
`CHANNELS`; nothing about the scheduler or the run lifecycle changes.

**Ingestion is still one offer per request**, so a worker that did collect something has no
cheap way to hand it over.
