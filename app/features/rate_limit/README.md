# rate_limit

Counts failed sign-ins and locks a bucket that fails too often. No router: nothing exposes
it, it is called by [users](../users/README.md) during authentication.

## How it works

Two buckets per attempt — one per account, one per address — each holding a count, a window
start and a lock. Crossing a limit locks that bucket, and the lock doubles with every
further failure up to a maximum.

**Counters live in PostgreSQL, not in process memory.** Several api replicas have to share
one budget, or the real limit is the configured one multiplied by the number of replicas.

**They are written through `session_factory`, outside the request transaction.** A failed
sign-in raises, the request rolls back, and a failure recorded on that session would roll
back with it — leaving the limiter counting nothing but successes. This is the second place
in the codebase that deliberately writes outside the request transaction; the other is the
[audit](../audit/README.md) middleware, for the same reason.

**The upsert is atomic.** Two attempts racing on one account would otherwise both read the
old count and store `limit - 1`.

## Decisions worth knowing before changing it

- Only credential failures are counted. An attempt made while a bucket is already locked
  raises before the password is checked, so hammering a locked account cannot extend its own
  lock. The count grows again once the lock expires, and that is what makes the next one
  longer.
- A successful sign-in clears the **account** bucket only. Clearing the address bucket too
  would let anyone holding one valid account wipe the budget for every account behind that
  address between guesses.
- Limits come from `settings`, never hard-coded at a call site — the tests read them from
  there too, so tightening one does not turn into a test failure.
- `RateLimitError` carries `Retry-After` through `AppError.headers`; there is still one
  error handler.
- Known gap: locking an account is a denial of service for whoever owns it. See `TODO.md`.

See also `.claude/rules/auth.md`.
