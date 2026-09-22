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
- [x] The first channel: `ksenukai-phones`, through the shop's search index. 520 phones
      collected end to end — discovered, snapshotted, handed over, contract passed
- [x] Layered reading: generic → category → source → brand → product → finish, each layer
      selected by a key that deepens down the list. On ksenukai's 520 phones it took
      `gtin 0 → 99.6%`, `model 0 → 100%`, `storage 0 → 97.9%`
- [x] The brand layer, with its tree: `normalization/brands/phones/{apple,samsung}.py`,
      selected from what the layers above read rather than passed in
- [ ] **Collapsing Apple's market code is declared and unwritten.** It would be correct on
      the collected data — nine configurations split, none disagreeing on capacity — and
      wrong on a larger corpus, where three prefixes of sixty-six differed on storage. It
      belongs to the identity key, which compares capacity at the same time instead of
      trusting a rule to remember.
- [ ] **The product layer is still empty.** Selectable by `(category, brand, line)` and with
      nothing registered; `bigbox-line` already writes the key it would be chosen by.
- [ ] **Samsung's part numbers cannot be cut yet.** `SM-A176BZ` begins six of them here and
      the letters after it are half colour and half region — telling those apart needs the
      colour table that does not exist, which is the same gap `phones-color` names.
- [x] The first canonical attributes, entered from what the two shops actually write:
      `storage_gb` and `color` bearing identity for phones, `ram_gb`, `screen_inch`, `os`
      and `phone_type` beside them. Seven alias spellings collapsed into five rows.
- [ ] **`color` has no values and no alias.** It bears identity for a phone and there is
      nothing to resolve a colour to — 61 spellings across 520 products, three problems in
      one shape. Its rule is declared `pending` and its registry row is empty on purpose.
- [x] The words a shop puts in front of a title live in the database, not in a rule.
      `category_aliases` holds one row per spelling, normalized the way it is looked up, and
      `Vocabulary` carries them into `read()` so that reading stays a pure function of what
      it was handed. Nine Latvian words entered for phones. The same table is what the
      unbuilt source-category mapping needs.
- [ ] **Nothing resolves an *attribute* name to the registry, so that vocabulary sits in code.**
      `attribute_aliases` and `attribute_value_aliases` exist for exactly this and both carry
      a `language` column; nothing calls either, so `categories/phones.py` holds Latvian
      strings as a marked stopgap. Category names took this route already, and attribute
      names are the same journey: a Lithuanian shop needs rows, not another tuple in a
      category module. The resolution
      cannot live in `read()`, which is pure — it is a second step over a stored reading,
      taking the offer's market for the language order (`markets.languages`, first is
      default) and falling back to aliases that belong to no language at all, which is what
      a maker's marketing names are.
- [x] The brand registry, seeded from what the two shops actually wrote: 62 spellings into
      52 brands and 54 aliases. `brand_unknown` went from 55 listings to none.
- [ ] **`Hammer` and `MyPhone` may be one brand.** 30 listings call Hammer a brand of its
      own and one shop writes `MyPhone Hammer Rock` in a title, so Hammer looks like a line
      myPhone makes. Left as two brands deliberately — it is written on the box, and
      `brand_aliases` allows one spelling to belong to two brands for exactly this. Decide
      it on more than thirty listings.
- [ ] **`No-Name` is not entered, and 4 listings say it.** A shop's way of saying unbranded.
      Entered as a brand it becomes the bin everything unrecognised falls into; left out,
      those four resolve to nothing, which is true. If more shops use it, it wants a real
      answer rather than an absence.
- [ ] **Nothing creates a variant from an offer**, so the catalogue is still empty and every
      one of the 1504 listings queues as `signals_unmatched` — correctly. 207 barcodes are
      shared between the two shops and 414 listings carry them, which is what the first real
      matches would be.
- [x] A signal that was used outranks one that was not: a barcode that was tried and
      missed is `signals_unmatched`, whatever the brand turned out to be
- [x] Promotion: a listing with a barcode from a trusted channel becomes a variant, joins
      the product for its brand and model, and carries its identity axes. 267 variants and
      202 products from the two shops, 610 of 1504 listings matched, and no entry merging
      two capacities — where the model rung alone had merged 44 of 96.
- [x] `bigbox-phones` reads a model out of its titles. The shop keeps one word order —
      `[kind] [brand] MODEL CAPACITY COLOUR` — so the model is what is left once the word
      naming the category and the brand are off the front and the title is cut at the first
      capacity; the colour needs no handling, it falls off with the capacity. 891 of 984
      yield one, and the names agree with what ksenukai states for the same phone
      (`iPhone 17 Pro`, `Galaxy S26 Ultra 5G`). Coverage went `model 0 → 90.6%`, and the
      shop's `no_model` refusals from 768 to 182.
- [ ] **93 bigbox listings still read no model**, and every one is a feature phone or a desk
      phone — there is no capacity in the title to cut at, and the colour then runs into the
      name, so two colours of one handset would file as two products. Left as a visible gap
      rather than guessed at. About 118 of the 891 also come out untidy, consistently so:
      the same phone yields the same string, so its variants still group, and what suffers is
      how the name reads rather than what it does.
- [ ] **`Tālruņa modelis` is read as a line and nothing selects on it yet.** It is on 40.5%
      of bigbox's phones and holds `Galaxy S26` for the Ultra, the Plus and the plain one
      alike — a family, not a model. `bigbox-line` writes it; the product layer that would be
      chosen by it is still empty.
- [x] Two pages to look at the result: `tools/preview.py` writes a storefront and a page
      of everything the matcher could not place, grouped by what is missing. Read-only and
      outside the app — the API serves JSON and there is no panel yet.
- [x] The queue was promoted: 195 new entries, 87 listings matched a variant the listing
      before them had just created. Matched went 1118 → 1400 of 1504.
- [x] The part-number rung checks the identity axes. Measured on bigbox, whose `mpn` is a
      model code, not a variant code: `CPH2865` is the Oppo Reno16 5G at 256 GB and at
      512 GB in two colours, and five of twenty matches on this rung had pulled two
      capacities onto one variant. A contradicting candidate is now dropped; one with
      nothing to compare is still taken, which is where it differs from the model rung.
      Merges on every rung: 0.
- [x] A confirmed model match keeps its barcode. 88 of the 207 barcodes the two shops share
      were on no variant, because the listings carrying them matched on the model and the
      barcode was tried, missed and dropped — the same work redone every pass. 492 barcodes
      learned, shared barcodes on a variant 119 → 207, the barcode rung 728 → 846 matches,
      variants present in both shops 134 → 173, products 100 → 129.
- [x] A third channel, `rdveikals-phones`, and the first that reads markup and the first
      with a cheap pass. 1394 phones, barcode on 10/10 of a live sample, colour as a field
      rather than a guess. Discovery is the listing, not the sitemap: walked the same
      afternoon the listing held 1400 and the sitemap 1382, neither contained the other, and
      every sitemap-only product sampled answered 404.
- [x] The collector read products one at a time. `Fetcher` had a semaphore for four and the
      worker awaited each product before starting the next, so three slots were always idle:
      1394 cards took 32 minutes at a rate that reads them in 10. Listing pages were serial
      too — 160 s, now 62 s.
- [x] The snapshot volume came up root-owned and the container runs as uid 1000, so every
      product failed to store and a run read as a shop that served nothing. Fixed in the
      `Dockerfile`, and `SnapshotStore.ensure_writable` now says so once, before the first
      request, instead of 1394 times.
- [x] The request rate is two settings that say what they are: `FETCH_CONCURRENCY` bounds
      how many requests are open, `FETCH_RATE_PER_SECOND` how many start per second. The
      delay used to sleep inside the semaphore, so the real rate was
      `concurrency / (delay + latency)` and the two knobs cancelled each other. Measured on
      a live shop: 2.23 products a second before, 6.31 after — a full pass of 1400 went from
      10.4 minutes to 3.7, faster than the legacy parser's documented 4.5.
- [x] Rules for `rdveikals-phones`. The model comes out of the name its analytics block
      records (`Kingkong Power 5 6/ 128GB Black`), cut at the first capacity: `model 0 →
      82.6%`. `Viedtālruņa modelis` is a line, not a model — `Google Pixel` on 27 phones —
      so it goes to `_line` like bigbox's. Stock on the cheap pass is read from the delivery
      estimate, measured against the pages: hours or minutes was `InStock` on 431 of 431.
- [x] A cheap pass no longer erases a catalogue reading. Whatever asks what a listing *is*
      reads the newest reading from a pass that carried the catalogue.
- [x] A guard against a rule body changing under an unchanged version, which had silently
      swallowed three fixes in one afternoon.
- [x] Colour, once a shop stated it as a field: 37 canonical values with their Latvian and
      plain-English spellings, read through the vocabulary the caller loads. `phones-color`
      was declared and unwritten from the start. The marketing names are deliberately out —
      the pairs learnable from one shop include `evening blue` meaning grey.
- [x] 18 brands a third shop brought, Sony among them.
- [x] An enum axis reaches the variant and takes part in the comparison, which the code said
      it could not until something resolved a value.
- [x] A match reconciles: it fills in axes the entry never had. Colour merges 327 → 157.
- [x] A match is only complete when every axis the *category* calls identity-bearing was
      known on both sides — not every axis the listing happened to carry. Two of three shops
      state no colour, so their listings agreed on everything they had, and that silence
      counted as agreement. Learned barcodes 478 → 35, entries holding two colours 157 → 50.
- [ ] **50 entries still hold two colours**, all of them between listings of the two shops
      that publish no colour at all. Nothing in the reading can separate them, so this is a
      collection problem rather than a matching one: either those shops state it somewhere
      not yet read, or a third shop's barcode has to arrive and split them. Worth measuring
      before anything is built — bigbox leaves colour in the title, which is the 358-form
      problem `phones-color` refuses on purpose.
- [ ] **Two shops disagree about three barcodes.** BigBox says `Iekšējā atmiņa, GB: 512GB`
      for a phone whose own title reads `4/128GB`, and lists 256 GB and 64 GB where
      rdveikals lists 128 GB and 256 GB for the same barcodes. We read the param over the
      title, which is right, and the shop is simply wrong. Three of 867 variants. Nothing to
      fix in the reader — but a disagreement on an identity axis under one barcode is worth
      surfacing rather than silently averaging.
- [ ] **243 rdveikals listings read no model**, every one a feature phone or a desk phone
      whose name carries no capacity to cut at (`GL695 Black`). The colour is there as a
      field on 99.9% and would settle them — which is the colour registry, below.
- [ ] **`rdveikals-color` is declared and unwritten, and it is now the cheapest it will
      ever be.** This shop states colour as a field on 99.9% of its phones in 37 forms,
      against the 61 a title yields. It is the missing identity axis, and the values are
      Latvian — so the work is `attribute_value_aliases` rows with a language, not a rule.
- [ ] **50 brand strings from rdveikals resolve to nothing.** Up from 4: a new shop brings
      new spellings, which is the brand registry's ordinary work.

- [ ] **`cron_full` and `cron_quick` are still null on all three channels**, so the
      scheduler has never started a run by itself and no channel has run twice. Without a
      second pass there is no price history, and `max_drop_pct` has nothing to compare
      against.
- [ ] **Nothing fills a product's own fields.** It gets a brand, a category and a model, and
      its title is composed from those. A description, an image and a manufacturer URL are
      what a card actually shows, and none of them are set.
- [x] A second channel, `bigbox-phones`: 984 phones, 98.7% deterministically identifiable,
      and 207 barcodes it shares with ksenukai — the first thing in this system there has
      ever been anything to match against
- [ ] **One more channel: `rdveikals-phones`.** The only one of the three that needs markup
      and therefore lxml; both shops read so far turned out to be the same third-party
      search index behind different keys. `1a.lv` is nearly free after ksenukai — same
      engine, different index — and it settles whether its product page carries a barcode
      at all.
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
