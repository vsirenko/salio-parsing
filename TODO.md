# TODO

What the project does not have yet, roughly in the order it should be picked up.
Tick items off here when they land so the list stays honest.

## Security — do before anything is exposed

- [ ] **`POST /api/products` is open to everyone.** Auth exists but was never applied to
      products. Decide the model: catalogue public for reads, writes admin-only, or the
      whole thing behind a client token.
- [ ] **Account lockout is a denial of service.** Rate limiting is per account, so
      someone who knows an email can keep that account locked by failing on purpose.
      The window caps it at roughly 15 minutes at a time, but it does not go away.
      Usually answered by keying the lock on (account, address) or by a CAPTCHA.
- [ ] **Sessions cannot be revoked one at a time.** The token epoch ends all of an
      account's sessions at once; there is no list of active sessions and no way to
      sign one device out. Needs a `refresh_tokens` table with `jti`, rotation and
      reuse detection.

## Operations

- [ ] **No CI.** Nothing runs the tests, ruff or `alembic check` on a pull request.
      GitHub Actions on the same commands the hooks use locally.
- [ ] **Nothing prunes `login_attempts`.** Buckets stop mattering once their window
      has passed, but the rows stay. `ix_login_attempts_updated_at` is there for a
      periodic delete; there is no job to run it yet.
- [ ] **Audit retention and backup.** The trail grows without bound and nothing prunes,
      archives or backs it up. Decide a retention window; partition by month if it gets
      large.
- [ ] **Audit writes fail open.** `AuditMiddleware` logs and swallows a failed write so
      the request still succeeds. If the trail becomes a compliance requirement, invert
      it so the action fails when it cannot be recorded.
- [ ] **Production DB grants.** The audit table should be INSERT + SELECT only for the
      application user, so append-only is enforced by the database and not just by us
      not writing an endpoint.
- [ ] **Observability.** Logs are plain text; no structured JSON, no error tracking
      (Sentry), no metrics.

## Features

- [ ] **No admin password reset.** An admin cannot set a password for a user who has
      forgotten theirs — only the account holder can change their own.
- [ ] **No password reset by email.** Blocked on there being no email at all; a
      forgotten password currently has no recovery path.
- [ ] **No password rules.** Only a length between 8 and 128 is enforced. No check
      against a breach list, no rejection of the obvious ones.
- [ ] **Products cannot be updated or deleted.** Create, list and get only.
- [ ] **No email.** Nothing verifies an address or sends a reset link.

## Nice to have

- [ ] Coverage gate in CI.
- [ ] Security headers and HTTPS redirect (usually terminated at the proxy).
- [ ] Background jobs, once anything needs to happen out of band.

## Done

- [x] PostgreSQL, SQLAlchemy 2.0 async, Alembic migrations, docker-compose
- [x] Readiness probe that actually checks the database
- [x] JWT auth with separate client and admin audiences
- [x] Audit trail of admin actions
- [x] Shared pagination, offset and cursor
- [x] User update and deactivation, with the panel protected from self-lockout
- [x] Self-service password change, ending every other session
- [x] Token epoch, so a password change or deactivation revokes stateless tokens
- [x] Per-account and per-address rate limiting on both sign-in endpoints
