## Users and access
- One `User` entity for both panels; `role` (`customer` / `admin`) decides where an account
  may sign in. Do not split into separate admin/customer tables.
- The security boundary is the token audience, not the table. Client tokens carry
  `aud=client`, admin tokens `aud=admin`; each panel decodes with its own expected audience,
  so a token from one is rejected by the other before any role check runs.
- Admin routes go on `admin_router` in `app/api/admin_router.py`, which carries
  `Depends(get_current_admin)` at router level — never guard admin endpoints one by one.
  `admin_public_router` holds only the routes that mint a token without one — login and
  refresh. Anything that takes a token, `/me` included, belongs on `admin_router`.
- Never use `UserInDB` as a `response_model` — it carries `password_hash`. Routes return
  `UserRead`.
- `role` is not accepted from any public input. There is no public registration endpoint;
  accounts are created through `/api/admin/users`.
- Passwords: argon2 via `app/core/security.py`. Never compare or store raw passwords.
- A password never travels through the user update schema. Changing one is its own
  endpoint, and changing your own means proving the current one first.
- Accounts are retired with `is_active = false`, never deleted. The audit trail points at
  the user row and keeps the actor's email denormalised for exactly this reason; there is
  no `DELETE /api/admin/users/{id}` and no service method behind one.
- A user edit must refuse to remove the caller's own admin access (`self_lockout`). That
  one guard is what keeps the panel reachable — the caller is by definition an active
  admin, so whoever else they demote or disable, one is left standing. Do not add a
  "last active admin" count next to it: it can never fire.

## Sessions and revocation
- A JWT carries no server state, so revocation lives on the account: `users.token_epoch`.
  Every token is minted at the account's current epoch and only that epoch is accepted.
- Mint through `_token_pair(user)`, which reads the epoch off the account. Never mint
  from a bare user id — a pair built at the wrong epoch is dead on arrival.
- Bump `token_epoch` from the service whenever access has to end now: password change,
  deactivation. One bump ends every session the account has, refresh tokens included.
- `UserService.get_for_token` is the single place that decides a valid signature is not
  enough. Both the access path in `app/api/deps.py` and the refresh endpoints of both
  panels go through it, so they cannot drift apart. A new reason to reject a token is a
  check inside it, never a check bolted onto one caller.
- The epoch is a counter, not a timestamp. JWT `iat` holds whole seconds, so a
  time-based epoch lets a token minted in the same second survive the change meant to
  kill it.

## Sign-in rate limiting
- Both login endpoints go through `LoginRateLimiter` (`app/services/rate_limit.py`),
  keyed per account and per address. A new endpoint that accepts a password takes the
  limiter with it.
- Counters live in PostgreSQL, not in process memory: several api replicas share one
  budget, otherwise the effective limit is the configured one times the replica count.
- Only credential failures are counted. An attempt made while a bucket is locked is
  refused before the password is checked, so hammering a locked account cannot extend
  its own lock — that is deliberate, not an oversight.
- A successful sign-in clears the account bucket only. Clearing the address bucket as
  well would let anyone holding one valid account wipe the budget for every account
  behind that address.
- Limits come from `settings`, never hard-coded at a call site. Tests read them from
  there too, so tightening a limit does not turn into a test failure.
