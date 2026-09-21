# users

Accounts and sessions, for both panels. One `User` row per person; `role` decides which
panel they may sign in to.

## Endpoints

| | |
|---|---|
| `POST /api/auth/login` | customer sign-in |
| `POST /api/auth/refresh` | exchange a refresh token for a new pair |
| `POST /api/auth/password` | change your own password, returns a fresh pair |
| `GET /api/auth/me` | current customer |
| `POST /api/admin/auth/login` | admin sign-in |
| `POST /api/admin/auth/refresh` | refresh the admin session |
| `POST /api/admin/auth/password` | change your own password, returns a fresh pair |
| `GET /api/admin/auth/me` | current admin |
| `GET · POST /api/admin/users` | list and create accounts |
| `GET · PATCH /api/admin/users/{user_id}` | read or edit one |

`router.py` is the customer side. `admin_router.py` holds three routers: `auth_public_router`
for the two routes that mint a token without one, `auth_router` and `users_router` for
everything that needs one.

## How it works

**The boundary is the token audience, not the role.** A client token carries `aud=client`,
an admin token `aud=admin`, and each panel decodes with its own expected audience — so a
token from one panel is rejected by the other before any role check runs. The role check in
`get_current_admin` is the second lock, not the first.

**Revocation lives on the account.** A JWT carries no server state, so `users.token_epoch`
does: every token is minted at the account's current epoch and only that epoch is accepted.
Bumping it ends every session the account has, including refresh tokens. It is a counter
rather than a timestamp because JWT `iat` holds whole seconds, and a token minted in the
same second would survive a time comparison.

**`get_for_token` is the single gate.** Every reason a valid signature is not enough —
deleted, disabled, moved to the other panel, signed out — lives there, and both the access
path (`app/api/deps.py`) and the refresh endpoints of both panels go through it. A new
reason is a check inside it, never one bolted onto a caller.

**Mint through `_token_pair(user)`**, which reads the epoch off the account. A pair built
from a bare user id would be dead on arrival.

## Decisions worth knowing before changing it

- A password change returns a fresh pair rather than 204, so the caller is not signed out
  by their own request. Every *other* session dies.
- A wrong current password is 422, not 401: the caller is signed in and their token is
  fine, and a 401 would send a client into its token-refresh path for no reason.
- A user edit refuses to remove the caller's own admin access. That one guard is what keeps
  the panel reachable — the caller is by definition an active admin, so whoever else they
  demote, one is left standing. Do not add a "last active admin" count; it can never fire.
- Accounts are retired with `is_active = false`, never deleted. The audit trail points at
  the user row.
- Sign-in goes through the [rate_limit](../rate_limit/README.md) feature.

See also `.claude/rules/auth.md`.
