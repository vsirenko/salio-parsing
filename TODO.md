# TODO

What the project does not have yet, roughly in the order it should be picked up.
Tick items off here when they land so the list stays honest.

## Security — do before anything is exposed

- [ ] **`POST /api/products` is open to everyone.** Auth exists but was never applied to
      products. Decide the model: catalogue public for reads, writes admin-only, or the
      whole thing behind a client token.
- [ ] **No rate limiting on sign-in.** Passwords can be tried without limit; argon2 only
      slows it down. Needs a per-IP and per-account limit on `/api/auth/login` and
      `/api/admin/auth/login`.
- [ ] **Refresh tokens cannot be revoked.** They are stateless, so "sign out everywhere"
      is impossible. Add a `jti` denylist (Redis) or rotation with reuse detection.

## Operations

- [ ] **No CI.** Nothing runs the tests, ruff or `alembic check` on a pull request.
      GitHub Actions on the same commands the hooks use locally.
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

- [ ] **User management is incomplete.** There is create, list and get; there is no
      update, deactivate, delete, password change or password reset.
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
