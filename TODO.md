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

- [ ] **Tests read the developer's `.env`.** Settings are one module-level instance built
      from it, so a value set locally changes what the suite asserts — it has already made
      one test pass or fail depending on whose machine ran it. The fix is a settings
      override for the test session, not a `finally` in each test that happens to care.
- [ ] **No CI.** Nothing runs the tests, ruff or `alembic check` on a pull request.
      GitHub Actions on the same commands the hooks use locally.
- [ ] **Nothing prunes `judge_verdicts`.** The store only grows, and a question keyed by a
      listing's title is answered again the moment that title changes, so the old row stops
      being reachable without ever being unreachable to a query. Needs a retention rule.
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
- [x] A source describes a channel — `access`, `decode`, what each pass delivers — rather
      than a format, with its schedule and contract thresholds beside it
- [x] `runs`: one execution of one channel, its measured coverage, and a contract that
      gates the absence inference rather than the writes
- [x] The scheduler process: advisory lock, startup sweep, one subprocess per run, bounded
      concurrency, timeout
- [x] Snapshots on the worker's disk, and a `reparse` run that re-reads them with the
      parser as it is now — the only way a parser fix is judged without crawling again
- [ ] **A worker takes the first of a shop's markets.** Right while a shop is shown in one,
      a fudge the moment it is shown in two: the offers of a Latvian and a Lithuanian
      storefront would all be filed under whichever market sorted first.
- [ ] **Nothing fetches.** The scheduler starts runs, spawns workers and records verdicts;
      `worker.py` has an empty `CHANNELS` registry, so every run ends as a failure naming
      the channel it could not collect. Adding a channel is adding an entry — the run
      lifecycle does not change. `source.base_url` is still filled in by nobody.
- [x] Batch ingestion, gzipped, partial on failure, one audit entry per batch, carrying
      the run that collected it
- [x] A collector audience: `aud=worker`, its own account, five routes and no more, so a
      parser does not hold an administrator's credentials while chewing hostile input
- [ ] **Workers still run only where the scheduler is.** They reach the service over HTTP
      now, so moving them onto another machine needs a claim endpoint — the scheduler
      currently spawns subprocesses rather than handing work out.
- [x] Price history and availability history, two series keyed by the listing rather
      than the variant, both partitioned by month
- [ ] **Availability has only one way in.** It is read out of whatever the main source
      served, alongside the price. A stock ping, a webhook or a faster poll would each be
      its own source writing only to `availability_events` — the table is shaped for that
      and nothing does it yet.
- [ ] **Nothing rolls new partitions.** Both event tables got fourteen months from their
      migration and a default partition catches anything past them, so inserts keep Fourteen months were created by the
      migration and a default partition catches anything past them, so inserts keep
      working — but rows piling up in a default partition cannot later be moved into a
      real one without rewriting them. A job has to create the next month before the last
      declared one runs out.
- [ ] **A fresh schema built from the models has no partitions.** `create_all` builds the
      partitioned parent and nothing else, so every insert fails with "no partition
      found". The test fixture creates a default one for each; anything else that
      bootstraps without migrations has to as well.
- [x] Matching on three deterministic rungs, with a queue that says why a listing could
      not be placed, and a summary that counts what actually happened
- [ ] **Load a real sample and read `GET /api/admin/match-queue/summary`.** Which bucket
      fills decides what to build next, and only real data answers it: mostly
      `signals_unmatched` means creating variants, `brand_unknown` means naming brands,
      `no_signals` means extraction; `brand_ambiguous` and `ambiguous` are the two a pair
      judge helps with, because they are the two that arrive with their candidates.
- [ ] **No fuzzy rung, so `low_confidence` has no producer.** Matching on a model needs
      the string to agree exactly after normalization. A near miss is invisible, which
      means a typo in a feed lands in `signals_unmatched` looking like a missing variant.
- [ ] **No `identity_key` rung.** It needs an offer's attributes resolved to the canonical
      registry, and nothing resolves them — the raw pairs sit in `normalized_offer`
      untouched.
- [ ] **No per-brand extraction rules.** The model is taken from whatever field the source
      called `model`, falling back to the whole title. Samsung, Bosch and Apple name models
      by incompatible conventions and one regex will not read all three.
- [ ] **A listing with no brand stated is filed as `signals_unmatched`**, which reads as
      "create the variant" when the truth is that the brand rung never ran. The reason is
      honest about the other four cases and wrong about this one; the fix is either its own
      reason or routing it to extraction, and which depends on how common it turns out to
      be.
- [x] A judge on `brand_ambiguous`, through TypeSafe: a `Choice` over the candidate
      brands described by what the catalogue holds under each, with the answers stored so
      a question is asked once. The matcher reads verdicts and never calls out.
- [ ] **The judge has never answered a real question.** Every test replaces the transport,
      so the wire format, the question body and the decoding are exercised and the model's
      behaviour on this catalogue is not. Nothing is known yet about how often it is right,
      what it costs per thousand listings, or whether `JUDGE_MIN_CONFIDENCE=0.85` is
      anywhere near the correct line. Needs an API key and the real sample.
- [ ] **No judge on `ambiguous` or `low_confidence`.** Those are variant pairs rather than
      brand options, and the shape that fits them is TypeSafe's entity-alignment recipe — a
      `Score` over three levels with `Noul` companions per field, not a `Choice`. Worth
      building after the summary says how full those buckets are.
- [ ] **A brand with no variants cannot be judged.** The options are described by the
      categories the catalogue holds under each brand, so a brand with nothing under it gets
      no description and the answer comes back unconfident by design. A human-written note
      on the brand row would cover the cold start; there is no column for one.

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
