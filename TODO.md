# TODO

What the project does not have yet, roughly in the order it should be picked up.
Tick items off here when they land so the list stays honest.

## Security — do before anything is exposed

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
- [ ] **Audit writes fail open, and it has already hidden a bug.** `AuditMiddleware`
      logs and swallows a failed write so the request still succeeds. Passing a `Decimal`
      to `record_changes` made the JSONB write fail; the endpoint returned 200 and simply
      left no record. Either make the serializer tolerate what services pass, or invert
      the middleware so an action fails when it cannot be recorded.
- [ ] **Production DB grants.** The audit table should be INSERT + SELECT only for the
      application user, so append-only is enforced by the database and not just by us
      not writing an endpoint.
- [ ] **Observability.** Logs are plain text; no structured JSON, no error tracking
      (Sentry), no metrics.

## Parser

The reason this repository exists, and none of it is built. The shape it should take,
and the questions that have to be answered with real data first, are written down in
[docs/parser-design.md](docs/parser-design.md).

- [x] Currency and country reference tables, admin-managed, seeded with the three
      Baltic markets. VAT rates are left null deliberately — see the migration.
- [ ] **Fill in the VAT rates** for LV, LT and EE. They were not seeded because they
      change and are not ours to guess; nothing computes with them, but they are what
      explains a price difference between markets.
- [x] Category tree with cascading visibility, and the canonical attribute registry
      with its aliases and per-category identity flags
- [x] Brands, their aliases and the resolver the matcher will call
- [x] The catalogue: products, variants, their attributes, barcodes and part numbers,
      with the title, slug and identity key derived
- [x] Shops, the sources we read them through, the sellers behind them, and which
      markets they are shown in
- [ ] **Nothing knows where a shop delivers.** `shop_markets` records where its offers are
      shown, and a human fills it in. A feed rarely states which countries it ships to and
      a scraped page states it in prose, so until that is solved "cheapest" on a card is
      cheapest for somebody rather than for the person reading it.
- [ ] **Merging a variant is not built.** The tables are there so an id survives being
      merged away, but the operation has to move offers and price history with it and
      neither exists yet. Until it does, a duplicate found by the identity key can only
      be reported, not resolved.
- [ ] **Images are hotlinked.** `variant.image_url` points at a shop's CDN, so it rots
      when that shop removes the file and we serve it from someone else's server in the
      meantime. The answer is to store the image, and there is no file storage.
- [ ] **The candidate queues are not built.** `attribute_candidate`,
      `attribute_value_candidate` and `brand_candidate` are what turns an unknown string
      into a mapping, and they are filled by ingestion — which does not exist yet. Build
      them with the parser, not before: a queue with no producer is furniture.
- [ ] **Nothing extracts attributes.** The registry can be filled by hand; pulling
      `256GB` out of a title still needs per-category patterns, and that is what
      `identity_ready` on a category is actually asserting.
- [x] Offers, raw observations and versioned readings, with ingestion by POST
- [ ] **Load a real sample and read `GET /api/admin/offers/coverage`.** The measurement
      everything else is downstream of, and there is now something to measure it with:
      30-50 real offers from both kinds of source, with the same product sold by more
      than one shop. Above roughly 90 per cent deterministic, build the matcher as
      designed. Around 40, the centre of the work moves to pulling identity out of titles.
- [ ] **Nothing fetches.** Ingestion takes a payload over HTTP; getting the payload is
      per-source work that has not started, and `source.base_url` is filled in by nobody.
- [ ] **Nothing matches or records a price.** `offer_match` and `price_event` are the last
      two tables of the design and both are shaped by the number above.

## Features

- [ ] **No admin password reset.** An admin cannot set a password for a user who has
      forgotten theirs — only the account holder can change their own.
- [ ] **No password reset by email.** Blocked on there being no email at all; a
      forgotten password currently has no recovery path.
- [ ] **No password rules.** Only a length between 8 and 128 is enforced. No check
      against a breach list, no rejection of the obvious ones.
- [ ] **No email.** Nothing verifies an address or sends a reset link.

- [ ] **There is no public read API at all.** Everything is behind `/api/admin`; the
      customer panel can sign in and change its password and nothing else. Whatever the
      storefront turns out to be, it reads through something that is not designed yet.

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
