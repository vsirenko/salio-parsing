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
- [x] ksenukai states no colour field, but its titles end the same way on 487 of 525 —
      `…, 256 GB, melna krās.` — and a case in two colours says the word twice. Reading that
      fixed position through the registry took its colour from 0 to 63.4%, and variants
      carried by more than one shop from 499 to 592. Four Latvian declensions were the bulk
      of what did not resolve: `melns` alone is 101 listings.
- [x] `identity_key` has values for the first time — 1191 variants. It needs every
      identity-bearing axis, so before colour existed it could not be computed for any.
- [x] The promotion pass runs each listing in a savepoint. A service answering a conflict
      with `session.rollback()` inside a bounded loop does not undo one listing: it empties
      the transaction and the pass then fails on the *next* listing with a lazy load that
      cannot run.
- [x] A clash on `identity_key` is asked about before the write rather than discovered by a
      failed flush. The answer to that conflict is itself a query, and a spent session
      cannot serve it — which is how a real duplicate surfaced as a 500.
- [ ] **67 entries hold two colours**, up from 50 because more listings now carry one and
      the disagreements that were silent are visible. `variant_merges` exists and nothing
      produces a row in it: two entries that reach the same identity are the same thing, and
      saying so is the point of the table.
- [x] A tenth channel, `tet-phones` (tet.lv), the first operator and the one that states
      most on its listing: the price, the stock flag and the manufacturer's code on 333 of
      333 cards, so six requests are a complete cheap pass. Barcode 98.1%, model 100% (126
      distinct), price 100%, availability 100%; it places 319 of 319. The contract-price
      worry that kept the operators waiting does not apply to it — its shop sells outright
      at a full price and the monthly figure beside it is a payment plan, the same one
      euronics shows.
- [x] `schema.org/InStock` means the shop will sell the thing rather than that it has it,
      on four shops in a row. Written into `.claude/rules/reading.md` rather than into a
      fifth module docstring.
- [x] A ninth channel, `discover-phones` (discover.lv), the first that reads XML and the
      cheapest here: `/catalog.xml` is the whole shop in one request, 560 of its 2768
      products are phones, and no product page is opened at all. Model 100% (135 distinct),
      brand 100%, availability 100%, colour 92.3%, and no barcode or part number anywhere on
      the shop. Its `trust` was set to `medium` at first and that was wrong: promotion
      refused 335 of its listings as `source_not_trusted` and the shop sat at 36.6%. Its
      data is as complete as onea's, which is `high` for the same reason — no identifiers
      but a clean name — so it is `high` too, and it places 521 of 560 and brought 306
      catalogue entries nobody else sells, mostly older iPhones.
- [x] An eighth channel, `cec-phones` (shop.cec.lv), the smallest here and the most
      targeted: 92 iPhones from an Apple Premium Reseller in two requests. Its twelve
      catalogue entries are all configurable and the variants are the offers. It publishes
      no barcode at all — its schema has no field for one — and that turns out not to
      matter: its `sku` is Apple's own code and 89 of the 92 were already here, carried by
      up to four other shops each. The brand is supplied by a rule, because the shop states
      none in any of a product's 41 fields; the inference is checked rather than assumed,
      since all 89 known codes are published under Apple elsewhere.
- [x] cec's colours, entered from evidence rather than judgement: the 89 Apple codes it
      shares with other shops say what those shops call each phone, and three labels came
      back unanimous — `Sudraba krāsas` silver (49 votes), `Lavandas krāsas` purple,
      `Astromelns` black. Entered; cec went from 19 unplaced to 8. `Ledāju krāsas` (white
      17 / blue 8) and `Night Sky` (no evidence at all) are left as visible gaps, which is
      what the disagreement is for.
- [x] `Ledāju krāsas` — Apple's `Glacier` — entered as white, and the first reading of the
      evidence was wrong because it was counted at the wrong grain. Summed over the label as
      a whole the shops looked split, white 17 against blue 8. Counted **per part number**
      they are not: on every one of the eight codes, bigbox, onea and dateks say white and
      only euronics says blue, and the catalogue entry those three already share is white.
      cec is now placed in full, 92 of 92.
- [x] **A marketing colour name can be settled from the corpus, and there are two ways —
      which one applies depends on whether the shop names its products.** Where a listing
      carries a per-product identifier, ask the shops holding the same one: that settled
      cec's `Sudraba krāsas`, `Lavandas krāsas`, `Astromelns` and `Ledāju krāsas`, and it is
      exact. Where it does not — discover.lv publishes only a family code, `SM-A576B` — that
      method returns every colour the phone comes in and is useless. The second way keys on
      the **word**: a marketing name appears in many shops' titles, and those shops state
      the colour in a field of their own, independently of it. Measured across the ten:
      `Obsidian` black on 97 of 97 across seven shops, `Midnight` black on 61 of 70 across
      eight, `Lilac` purple on 8 of 8 across four, `Lightgray` grey, `Iris` blue,
      `Mint Breeze` green. Entered. `Fog` (green 9, light-green 4, grey 2), `Frost` (blue 6,
      purple 3, black 3), `Canyon` (pink 8, orange 3) and `Charcoal` (black 11, grey 6) are
      genuinely contested and were left alone — a marketing word can mean different colours
      to different makers, and the registry has no brand to hang that on.
- [x] **A marketing colour name belongs to a maker, and the registry cannot say so.**
      Counted across all shops the words looked contested; counted per maker one of them
      proves the point outright: `Canyon` is **pink on a Google** (8 of 8, two shops) and
      **orange on an Oppo** (3 of 3, two shops). A global alias would make one of them
      wrong, so none of these were entered. `attribute_value_aliases` has a `language`
      column and no brand, and the layer that selects on `(category, brand)` already exists
      — `brands/phones/apple.py` and `samsung.py` — so a maker's palette belongs there or
      behind a brand column, and it is a decision rather than a row.
- [x] The four brands entered earlier — `CAT`, `TTfone`, `XREAL`, `Lenovo` — never worked:
      creating a brand does not create an alias on its own name, and only `Caterpillar` was
      added beside `CAT`. All four resolved to nothing. Self-aliases added, plus `HTC` and
      `Umidigi`, which were missing outright. `brand_unknown` in the queue: 12 → 0, corpus
      98.4% → 98.5%.
- [x] **The judge was asked something, for the first time.** Not the question it already
      knew — a brand string meaning two companies does not occur here, no alias in the
      registry leads to two brands and the queue has never held a `brand_ambiguous` row. And
      not the brand disagreement either: measured across 6321 listings, a field and a title
      naming different known makers happens **twice** (`HMD 2660 FLIP` filed under Nokia,
      `Umidigi Bison X10` under CAT), which is not worth touching the ladder for.
      What it was asked is `variant_choice`: which of several entries differing in one axis
      a listing is. Five real questions, 3103 input tokens. It placed nothing and every
      refusal was right — `Awesome Charcoal` at 0.48 where the corpus is split black 5 /
      grey 4, and a three-tone UleFone where the catalogue genuinely holds no such entry.
      The third answer, `titanium` at 0.81, fell below the 0.85 threshold and was a
      refurbished phone that should not have been in the question at all.
- [x] **The judge names a colour, which is what the entry question turned out to need.**
      `variant_choice` refused 30 of 30 and was right to: at confidence 1.00 a `Coralred`
      Samsung is neither of the entries the catalogue holds. Those listings do not want an
      entry chosen, they want one made, and the promotion bar stops them because it asks for
      every identity-bearing axis and the colour is missing. `colour_choice` asks about the
      **whole title** plus the maker — 53 of the 57 keep the colour there and no rule may cut
      it out of a title — and answers with one of the registry's 37 plain colours.
      `POST /api/admin/matching/judge/colours`.
      The answer does **not** become an `attribute_value_aliases` row, which is where the
      plan started and is wrong for the same reason the counting was: that table is global,
      `Canyon` is pink on a Google and orange on an Oppo, and an alias learned from one
      listing would be applied by the reading to the other maker's phone. It is read where a
      bought brand is read — `MatchingService._identity` — so the reading stays a pure
      function of a payload and its rules.
- [ ] **A title that names a different maker than the field is a question for the judge.**
      discover.lv files `Umidigi Bison X10` under `CAT`, its own section name, and now that
      `CAT` resolves the listing goes there confidently — the title fallback deliberately
      does not second-guess a brand that resolves, which is right in general and wrong here.
      Two signals disagreeing about a brand is exactly what `judge_verdicts` and
      `brand_ambiguous` were built for, and the judge has still never been asked anything.
- [x] **A maker's palette is code, in the layer that selects on `(category, brand)`.** The
      registry cannot hold it — `attribute_value_aliases` is keyed on the word and a
      language with no brand, and `Canyon` is pink on a Google and orange on an Oppo — so it
      goes in `brands/phones/`. `google-phones-2`: `canyon` pink (2 shops of 2), `jade`
      green (2 of 2), `indigo` blue (3 of 3), `porcelain` white (6 of 7), `fog` green
      (3 of 4); `frost` declared and unwritten, rdveikals purple 12 against euronics blue 6.
      `samsung-phones-1`: `cobalt` purple (9 of 9, 217 listings), `silverblue` silver
      (6 of 7), `jadegreen` green (5 of 5), `techno` purple (4 of 4), `whitesilver` white
      (4 of 5), `blueberry` purple (3 of 4), `graygreen` green (2 of 3), `amber` yellow
      (2 of 2); `charcoal`, `coralred` and `pinkgold` declared and unwritten.
      Counted **per shop**, not per listing: five listings of one phone in one shop is one
      opinion, and counting listings is what made these words look contested before.
- [x] **m79.lv, the eleventh shop and the cheapest full pass of the eleven.** 2693 phones in
      22 seconds and not one product page opened: the listing card carries the id, the
      title, the price, the stock word, the shop's item code as base64, and the barcode in
      the product's own address — `barcodes.pick` finds a valid one on 72% of them, beaten
      only by two of the other ten. Two traps, both measured before the channel was written.
      A **numeric path segment is looked up as a product code before it is a page number**:
      `/mobilie-telefoni/150` served a board game whose `Preces kods` is 150, and `/250` a
      toy truck, so two of five sampled page numbers silently swallowed a page of products.
      And the **page size is not a query parameter** — four guesses at one were wrong; it is
      `POST /ajax/set-setting` with `settingValue=96` against the session cookie, which
      takes the walk from 314 pages to 40 and the collision surface with it. The shop
      ignores that POST until it has a session, so the channel checks the page it gets back
      and asks again rather than trusting it — one run walked the category twelve to a page
      believing it was walking it ninety-six to a page.
- [x] **A listing with no brand field at all now reads the title for one.** `_resolve_brand`
      returned `none_given` and stopped, because the title fallback was written for a shop
      that states a brand nobody knows. A shop that states none is not a shop stating one
      correctly, so there is nothing to second-guess and the risk is strictly lower. m79 is
      why: it names a maker in a field on 28% of its listings and in the title on almost all
      of them, and without this 425 fully-read phones could not become a catalogue entry.
      Promotion refusals for `brand_unresolved` went 425 -> 84.
- [x] **Three causes held two hundred listings, and all three were measured before they
      were touched.** A power bank is a battery, so `Akumulatora ietilpība` could never say
      "this is a phone" — it let eleven of them in along with a pair of Bose headphones, and
      the channel now asks for a SIM slot or internal storage instead. A brand read off the
      title failed where the shop puts the kind in front of the maker — m79 writes
      `Smartphone Apple iPhone 16 Plus`, so 79 listings with a barcode and a good model sat
      unplaced; the model is tried after the title now, because the shop's own ruleset has
      already taken those words off it. And the colour rule refused every phrase: `Titanium
      Silver`, `Midnight Blue` and `Glacier Blue` each carry two entries the registry knows,
      and counting distinct values threw all of them away — 130 listings, of which 99 are a
      single phrase. A run breaks on anything but a space, because `Black/Orange` means
      both and joining those reads it as `orange`.
      Corpus 96.4% -> 97.4%, queue 336 -> 245, `brand_unresolved` 113 -> 29.
- [x] **`titanium` is a material and the registry called it a colour — removed.** It was
      winning over the real colour: `Blue Titanium` read as titanium, and two catalogue
      entries held the desert, the natural and the white iPhone 16 Pro Max as one product
      with their prices compared as one. Removing the value and its two aliases, and
      clearing the axis off the 23 variants that held it, let 205 of the 248
      titanium-titled listings read a real colour — black 73, silver 44, grey 30, blue 23,
      white 19. It also unblocked Samsung's `Titanium Silverblue` line, which was the known
      cost written down when the title rule landed.
      What was left is Apple's own phrases, now in `apple-phones-2`: `desert titanium` gold
      (one Apple shop states it, and `desert` reads gold in 4 shops of 4 across every maker
      that uses the word), `natural titanium` grey (one shop, 5 listings, uncontested).
      `lunar titanium` and `stellar titanium` are declared and unwritten — `lunar` gets four
      different answers from four shops.
      `colours.from_title` takes multi-word keys for this, which is what Motorola's forty
      PANTONE names will need too: `Cosmic Orange` and `Cosmic Black` share a word and are
      two colours, so the word is not the unit.
- [x] **A barcode we inferred now yields to a contradiction; one a shop published does
      not.** 480 live matches had a colour the entry contradicted, all of them on the GTIN
      rung, and the split is the whole point: 431 sit on a barcode a shop published, where
      two shops call one phone `graphite` and `grey` and disagree about a shade rather than
      about which phone it is. The other 49 sit on a barcode `_learn_gtin` inferred, and 40
      of those are a different colour family — black against orange, white against green.
      One was traced end to end: a bigbox `White Titanium` listing with no barcode became an
      entry, an rdveikals `Natural Titanium` listing matched it on the model while both
      still read `titanium`, the match looked complete because the wrong axis agreed, and
      the entry was given that listing's barcode. From then on the listing found itself by
      that barcode on every pass and the rung never looked at a colour.
      No guard on `_learn_gtin` could have caught it — a wrong reading looks exactly like a
      right one — so the fix is downstream: a learned barcode is our own conclusion and a
      conclusion the axes contradict falls through to the rungs below, which weigh them.
      Wrong matches retired: 49 -> 21, and the listings are back in the queue where they are
      visible.
- [x] **The maker is read from the end of a title as well as the front.** A whole supplier
      feed at m79 writes it last, in front of the shop's own suffix: `MOBILE PHONE GALAXY
      FOLD7/512GB SM-F966B SAMSUNG Mobilais Telefons`. Read from the front the first two
      words are the kind and the maker is nowhere. Only the last four words and one at a
      time, because a maker's name anywhere in a title is not a claim that the maker made
      the thing — `Case for iPhone` is the shape that would go wrong. With four product
      lines entered as aliases of their one maker — `iphone`, `galaxy`, `pixel`, `redmi` —
      promotion refused for want of a brand went 26 -> 8 and the corpus 97.5% -> 97.8%.
      `ambiguous` grew 39 -> 55 in the same pass, which is the listings moving from "no
      maker" to "which of these entries", and is the better question to be stuck on.
- [x] **Twenty-one of them come back on every pass.** They did not: the count was taken
      mid-loop, before promotion and merging had run. One round in the right order —
      retire, match, promote, merge, retire again — leaves a single listing, and that one
      falls to `low_confidence` rather than to a wrong entry.
- [ ] **`phones-color-from-title` and `ksenukai-color-from-title` are two implementations of
      one idea.** The source-level one came first and reads a fixed position in that shop's
      titles; the category one reads any registry word anywhere. Keeping both is how the
      same three lines end up written twice with the same bug — which is exactly what
      produced `naming.without_brand` earlier. Measure what ksenukai loses if its own rule
      goes, then delete one of them.
- [x] **OnePlus has a palette now**, counted the same way as the others: `charcoal` black
      3 shops of 3, `pitch` black 3 of 3, `phantom` grey 3 of 3, `eclipse` black 2 of 2,
      `mist` grey 5 of 6, `marble` grey 5 of 6, and `dry ice` blue by a decision — one shop,
      3 listings, nothing against it, and a phrase because neither half names a colour.
- [x] **`coral` is gone from the registry and `Coralred` is red.** bm said red on 4 and
      rdveikals coral on 3, one shop each, and it was never a disagreement about the colour
      — only about how finely to name it. 2 catalogue entries and 2 listings sat under
      `coral` against 73 and 169 under `red`, so it divided the red phones and distinguished
      nothing. Same shape as `titanium`, much smaller.
- [x] **A shop that contradicts itself is no vote at all.** `Awesome Charcoal` read as 3
      shops for black against 2 for grey, which is not a majority worth acting on — until
      the votes were read: dateks says black on the Enterprise Edition of the A37 and grey
      on the plain one, the same phrase on the same phone. Without it the count is two shops
      to one, which is the ordinary bar, and the answer is black. Worth remembering as a
      way of counting rather than as a fact about charcoal.
- [ ] **Motorola and Honor still have palettes waiting.**
- [ ] **The word method is a script that was run by hand and ought to be a tool.** It is the
      answer to the registry gap this project has been carrying since the first shop, and it
      runs against the corpus rather than against anybody's judgement. Worth an endpoint that
      proposes aliases with their votes, for a person to accept — not one that enters them.
- [ ] **`Night Sky` still wants a photograph.** Apple's name for an iPhone Duo colour, on 4
      cec listings. bigbox carries the same codes and does not resolve it either, so there
      is no evidence to read — unlike Glacier, this one really is unknown.
- [ ] **euronics reads `glacier` as blue where three other shops read white.** It did no
      harm — those listings matched on a stronger signal and sit on the same entry — but it
      is a wrong colour on a reading, and the next product where it is the only signal will
      not be so lucky.
- [x] The catalogue was splitting one phone into two entries, and the cause was in the
      matcher: `_learn_gtin` ran only where the model rung fired, so a listing that matched
      by **part number** kept its barcode to itself. The next shop carrying that barcode
      found nothing and built a second entry beside the first — `PHONE WAVE 7C` and
      `Wave 7C`, `Edge 70 Fusion` and `Motorola Edge 70 Fusion`. It learns on that rung now,
      under the same guard, and the split is no longer reachable through the ladder: the
      test for the merge has to build one by hand.
- [x] `variant_merges` has a producer. `CatalogService.merge_variants` moves the listings,
      the identifiers and only the axes the survivor was missing — an axis both hold is left
      alone, because two entries disagreeing about a colour is a question and not something
      a merge may settle quietly. `POST /api/admin/matching/merge` finds the pairs, **only
      by barcode**: a part number names a family as often as a product, so two entries
      sharing one are usually two real configurations. 26 found, 26 merged, 0 refused;
      barcodes sitting on two entries went from 26 to 0.
- [x] Two shops were writing the working memory into the model, and the storefront showed
      it: discover.lv on 217 of its 560 names (`12/128GB` cut at the unit leaves `12/`, so
      `Pixel 10` became `Pixel 10 12`) and tet.lv on 189 of its 319 (`12+256GB`, where the
      capacity pattern finds `256GB` in the middle of the configuration — the cut is the
      **earliest** of the two matches, not the first one tried). Distinct models: discover
      135 → 117, tet 126 → 117. discover was also taking out any bracket to be rid of
      `(SM-S948B)` and cost `Apple iPhone SE (2022)` its year, which on an SE is which one
      it is; only the string the channel read as the family comes out now.
- [x] `POST /api/admin/matching/rebuild`. Fixing a reading does not fix the catalogue
      entries already named from it — they stand under names nothing reads any more. This
      renames an entry from its listing's current reading, and only where the entry has
      exactly one listing: two shops agreeing on an entry is evidence its name is good
      enough, and one of them disagreeing about a `5G` suffix is not a reason to rename what
      they share. A rename that collides is the answer rather than the problem — the
      identity key says the entry has become one that already exists, and the two are
      merged. 189 found, 142 renamed, 47 merged; then 14 more after tet was fixed. Junk
      entries carrying memory in their name: 251 → 62, and some of those 62 are real names
      like `Armor Mini 4`.
- [ ] **Six refurbished phones stand on entries for new ones**, showing their lower price
      as the cheapest. Three were tet's, whose filter knew `RENEWD`, `REFURBISHED` and
      `PRE-OWNED` and not the Latvian `[Mazlietots]` — widened, and the ones already
      collected are still there. The other three are at bigbox (`Renew Grade A+`), ksenukai
      and onea, whose channels have no such filter. Filtering in each channel is a
      workaround done three times now and missed once; the real answer is `offers.condition`,
      which exists, is `new` on all 6321 rows, and is read by neither matching nor the
      storefront.
- [ ] **145 part numbers still sit on more than one variant.** A barcode does not accuse
      them and never will, so this wants a different kind of evidence — the causes are a
      model string that differs between shops (`Find X9 Ultra` against bm's whole spec sheet
      used as one, `600 Smart` against `600 Smart 5G`) and a colour two shops disagree
      about. Some of those pairs are two real configurations and must not be merged.
- [ ] **bigbox's 50 unplaced listings are reachable, and not yet worth reaching.** Its
      model rule declines a title with no capacity in it, deliberately: on that shop it is a
      feature phone or a desk phone, and the colour runs into the name. Cutting a trailing
      colour off through the registry — rdveikals' technique — was measured at 58 of its 93
      model-less listings. The quality is not there yet: `GSM Nokia 106` and
      `KX-TS500PDB stacionārais` keep a category word the registry does not hold, a stylus
      reads as `Zīmulis Honor Magic Pencil`, and `NOKIA 200 4G TA-1785 DS` and
      `NOKIA 200 4G DS` would become two entries for one phone. Worth doing with the title
      cleaning done properly — adding `gsm`, `stacionārais`, `fiksētais` to
      `category_aliases` is most of it — and not worth doing by bolting it on.
- [ ] **bm.market's Apple codes are the first five characters of everybody else's.** It
      writes `MD1Q4` where the others write `MD1Q4HX/A`, so 46 of its Apple listings cannot
      match on a part number they in fact share. Apple's first five characters identify the
      configuration and the suffix the region, so within one market they are the same phone
      — but that is a matching decision about how much of a part number has to agree, not a
      reading one, and it wants deciding rather than assuming.
- [x] A seventh channel, `euronics-phones`, and the first that reads JSON-LD: 319 phones,
      discovery in **one request** — the `?f=` token is protobuf and its sixth field is the
      page, so a token built past the end returns the whole cumulative listing. Barcode
      100%, part number 100%, model 99.7%, price 100%, availability 100%, colour 97.5%, and
      the ruleset is a single rule because the shop states the rest outright. Two traps:
      `data-product-price` is the loyalty price on 51 of 319 (599.99 against 839.99), and
      `data-product-brand` is `Vaikimisi` — Estonian for "default" — on every card.
- [x] The category's colour rule looked its value up exactly, which is why the two shops
      that state a phrase rather than a word got nothing from it: `light blue`,
      `tumši zils`, 104 products between dateks and euronics. It resolves through `colours`
      now, which reads a phrase by dropping words off the front — 93 of them come in. The
      other 11 name two or three colours at once and are refused rather than reduced, since
      dropping words off the front reads `black, orange` as `orange`. The registry is asked
      about the whole phrase first: it knows `Melna / Oranža` as one alias, and taking that
      apart to put it back together turned a known answer into a guess — caught by a test
      that already existed.
- [x] A sixth channel, `bm-phones` (bm.market), and the first that reads GraphQL: 937
      phones in 5 requests and 74 seconds, no product page opened. Brand 99.9%, model
      100%, availability 100%, colour 90.1%, barcode 50.8%, part number 45.8% → 58.6%.
      Three traps, each of which reports success: the bigger of its two telephone
      categories is a section holding Apple Watches; `stock_status` is a constant
      `IN_STOCK` while `availability_type` says 934 of 937 are to order; and
      `manufacturer` is a Magento select, so the obvious query returns null for every
      brand and appears to work. For Apple — 42 barcodes on 196 products, the thinnest
      brand here — the part number is not missing but written into the name, and reading
      it there takes Apple from 41 to 161. Six shops: 5031 listings, 97.0% matched,
      variants 1768 → 2142, carried by more than one shop 1006 → 1118, 64 in all six.
- [x] A fifth channel, `dateks-phones`: 745 phones, model 100%, barcode 86.3%, colour
      97.3%, availability 100%. The shop had been written off as closed — it is not, and
      neither its Cloudflare nor our HTTP client was ever the problem: the category moved
      from `mobilie-telefoni` to `viedtalruni` and the old address still answers 200 with a
      page of navigation and no products. Two more traps measured rather than guessed: the
      page index in the address is one less than the page, so a walk starting at `/pg/1`
      drops the first 24 of 745; and the page's own schema.org `availability` reads
      `InStock` for all 745 where the shop's words say 524 are to order. Matching across
      five shops 98.1%, variants 1477 → 1768, carried by more than one shop 827 → 1006,
      135 in all five.
- [x] A fourth channel, `onea-phones` (1a.lv): 443 phones, model 99.6%, part number 44.5%,
      no barcode at all. Its index is a strict subset of ksenukai's — same engine, same
      field names — so the record shape and the colour rule are shared rather than copied.
      Variants carried by more than one shop 592 → 633, and 119 are now in all four.
- [x] BigBox resolved 0 colours of 985. It publishes no colour field and its titles were
      never read for one, though they end in a word the registry already held — which is
      why 147 listings reached a rung that found four entries differing only in colour and
      refused to choose while the listing said `Black` in its own title. Cut at the last
      capacity, drop a brand that follows the colour: 679 of 985. Plus 14 Latvian
      declensions. Colour across four shops 79.7%, variants carried by more than one shop
      633 → 732, by all four 119 → 132.
- [x] Two faults in reading a colour phrase, worth more than two hundred registry rows
      between them. The group writes the word for colour three ways — `krās.`, `kr.`,
      `krāsā` — and only one was read. And a phrase is now looked up by dropping words off
      the front, which resolves Samsung's `lieliski` (`Awesome`) line without this code
      holding a list of marketing prefixes: the colour is the head of the phrase and the
      head comes last. Not the other way round on purpose — `silver shadow` and `arctic
      seal` put the invention last, and guessing from the first word would read a seal as a
      colour. `normalization/colours.py` owns the decision for every shop, as
      `barcodes.py` does for its own.
- [x] 117 spellings of a maker's own colour names, written by hand into
      `attribute_value_aliases`. Nothing derives them — obsidian is black because Google
      decided so — and at this size a person writes them once and can read them back, which
      a probability cannot.
- [x] A reparse recomputes a reading instead of trusting the version. The version tracks
      the rules and a reading is a function of the rules *and* the words handed to them, so
      117 aliases entered in the registry moved no version, nothing looked stale, and
      nothing was recomputed: two shops kept readings with no colour while the words sat in
      the table. Colour went 90.6% → 95.4% the moment the re-read stopped asking.
- [x] ksenukai and 1a.lv leave the word for colour off 34 titles altogether and put the
      colour last behind a comma anyway. Read from there, with the registry still the gate.
- [x] A catalogue entry may be started by a barcode **or** by an identity complete enough
      that another shop would arrive at the same one. The first bar was the only one for as
      long as a barcode was the only thing two shops could agree on, and it left 1a.lv —
      which publishes none — unable to contribute anything: 27 listings fully read and
      invisible. 1a.lv placed 74.9% → 98.9%.
- [x] Among candidates that all agree, one that agreed on every axis the category names
      beats one that agreed on the two it happened to hold. An entry recording no colour
      agrees with every colour, and one of those beside a real one made every coloured
      listing of that model ambiguous — with the winner decided by arrival order.
      `ambiguous` 15 → 7.
- [ ] **Seven of those 117 are guesses and should be checked against a real product.**
      `arctic seal` and `silhouette` and `miglas` went to grey by how they sound;
      `carbon` is nearer dark grey than black; `black olive` is a dark *green* and was filed
      under black by its first word; `sky teal` sits between green and turquoise and we hold
      both; `fluidity` and `tapestry` are not colour words at all. And `evening blue` was
      filed as blue against the shop's own field, which called it grey. A wrong colour
      splits one product into several, confidently, so these are worth an hour with the
      product photos — or the first question the judge is ever asked.
- [ ] **Colour merges are a visibility number, not a quality one.** They went 327 → 157 → 50
      → 67 → 92 as colour reached more listings: each time more of them carry one, more
      previously silent disagreements become countable. Counting how many *could* disagree
      would say more.

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
