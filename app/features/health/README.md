# health

Two probes, deliberately different.

## Endpoints

| | |
|---|---|
| `GET /health` | liveness — touches nothing |
| `GET /health/ready` | readiness — runs `select 1` |

Mounted on the app directly rather than under `/api`, because an orchestrator should not have
to know the API prefix.

## How it works

**`/health` must never touch the database.** It answers "is this process alive", and a
database blip that made it fail would turn into a restart loop that fixes nothing.

**`/health/ready` answers "should traffic come here"** and returns 503 when the database is
down, which is what pulls the instance out of the load balancer while leaving it running.

No service and no state: a feature folder holds what that feature needs and nothing more.
