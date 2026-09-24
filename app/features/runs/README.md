# runs

One execution of one channel: starting it, judging it, and deciding what is due.

## Endpoints

| | |
|---|---|
| `GET /api/admin/runs` | what has been collected, newest first, filterable by `source_id` and `status` |
| `GET /api/admin/runs/due` | what the scheduler would start right now |
| `GET /api/admin/runs/{run_id}` | one run, with its coverage and verdict |
| `POST /api/admin/sources/{source_id}/runs` | start one by hand |
| `POST /api/admin/runs/{run_id}/finish` | a worker reporting back |
| `GET /api/admin/scheduler` | alive or not, what runs, what is due, and every channel's schedule, last run and next slot |

## How it works

**`runs` is the scheduler's memory, and `scheduler_heartbeat` is its pulse.** `runs`
answers when each channel last ran and what is running; with nothing due it says nothing,
and on 23.09.2026 that looked exactly like a scheduler that had stopped — no source had a
schedule, the log was empty, and the container's health check probed an HTTP port this
process does not open, so it read `unhealthy` whatever the scheduler did. Each tick now
rewrites one row, `GET /scheduler` calls it alive within three ticks, and the container
check is `python -m app.features.runs.scheduler --healthy`, which asks the same question.

**`runs` is the scheduler's entire memory of schedules.** It answers both questions the scheduler has:
when did this channel last run, and is it running now. There is no scheduler state anywhere
else, and deliberately no `next_run_at` column — that would be a cache of `cron + last run`
which goes stale the moment somebody edits a schedule, leaving two sources of truth to
disagree in silence. Seventy channels recomputed on every tick costs nothing.

**Everything the scheduler decides is an ordinary query**, which is why `GET /runs/due`
exists: what the process would start can be read, and asserted, without starting it.

**Two kinds that collect, `full` and `quick`,** and one that does not. A dedicated stock
endpoint is not a fourth — it is another channel into the same shop whose full pass happens
to carry availability and nothing else.

**`reparse` re-reads the snapshots already on disk** with the parser as it is now. No
network, no cron, never due: started by hand, after a parser is changed, which is the only
way a fix can be judged without crawling the shop again — and crawling again would measure
the site as it is today rather than as it was when the parser broke. It reads both areas,
and the failed one is the reason to run it at all: a product that would not parse is
exactly what the fix was for. One that parses now moves out of `failed/`; one that used to
parse and no longer does moves in.

A reparse must never earn the absence inference. It sees whatever happens to be in the
snapshot store, which is a subset by construction, so what it did not see means nothing.
Only a collecting run that ended `ok` may conclude a product is gone.

**A slot is read backwards, not projected forwards.** The most recent slot at or before now,
compared against the last start. Projecting forward from the last run means a channel that
has never run, or was off for a week, computes its next slot from a point so far back that
it is permanently outside the catch-up window and never starts at all. A slot missed by more
than six hours is let go rather than caught up: a crawl that late answers a question nobody
is asking, and the next one is along shortly.

## Decisions worth knowing before changing it

- **The contract gates absence, not writes.** A channel that returns three products instead
  of nine hundred has not lied about the three: they are real, and writing them harms
  nothing. The damage is concluding that the eight hundred and ninety-seven unseen ones are
  gone. So only a run that ended `ok` earns the right to treat what it did not see as gone,
  and no staging mechanism is needed to hold a batch until it is judged.
- **A drop is measured from the last run that ended `ok`**, not from the previous run of
  that kind. Against the previous one, two broken crawls in a row pass the second: it fell
  only a little, from an already-wrong number. There is a test that fails if this is changed.
- **The contract only asks about facts the channel claims to deliver.** Checking price
  coverage on a pass that never carries a price would reject every run of it, forever.
- **A worker that broke is not judged on its numbers.** `error` set means `failed` and the
  contract is `not_evaluated`: judging the counts of a crash is judging nothing.
- **A live run is exactly a row without `finished_at`**, tied to the status by a check
  constraint so the two cannot drift, and held to one per channel and kind by a partial
  unique index — by the database, rather than by the hope that only one scheduler exists.
- **`interrupted` is swept at startup, not timed out.** The scheduler is single by
  construction, so anything still running when it starts has no process behind it. The count
  is also an honest metric: it is how often we are being killed.
- **`coverage` is measured; `delivers_*` on the channel is declared.** The gap between them
  is the alarm. A channel whose `gtin` was 0.95 last week and is 0.10 today is a shop that
  changed something, found the day it happens rather than a month later through matching
  quietly getting worse.
- **A malformed cron is refused when it is written**, not skipped at tick time. Skipped, it
  stops that channel in silence: nothing fails, it simply never becomes due, and the first
  symptom is stale prices nobody can explain.

## The scheduler

```bash
python -m app.features.runs.scheduler          # the daemon; compose runs this
python -m app.features.runs.scheduler --once   # one tick and exit
```

Its own process rather than a thread inside the API, where it would be started once per
uvicorn worker and die with whichever one held it. Being the only one is a Postgres
advisory lock taken on a connection of its own — a pooled connection would be recycled and
take the lock with it, which is the quiet version of running two schedulers. A second copy
exits immediately, so scaling the service by accident costs nothing.

```
start   take the lock, or exit
        sweep: anything still running has no process behind it

tick    reap finished workers
        ask due(), start what there is room for, spawn one process per run

stop    wait for what is running, then reap so each one keeps its own verdict
```

**Products are read side by side; the rate is the fetcher's, not the loop's.** The worker
used to await each product before starting the next, which pinned every run to one slot and
left the rest idle: a shop of 1400 cards took half an hour to read at a rate that reads it
in ten minutes. The pool is sized to `FETCH_CONCURRENCY`, because a product usually costs
one request and more tasks than slots would only queue against the gate. A channel that
pages its listing does the same for the pages, which matters most on the cheap pass, where
the listing walk is the entire cost.

**Politeness is two numbers, not one.** `FETCH_CONCURRENCY` is how many requests may be
open at once; `FETCH_RATE_PER_SECOND` is how many may be started per second, whatever is
open. They were one number by accident: the delay used to be slept *inside* the semaphore,
so it held a slot and the real rate was `concurrency / (delay + latency)` — raising one and
lengthening the other cancelled out, and neither said what it meant. Measured against a live
shop, four slots and half a second gave 2.2 products a second; the same politeness expressed
as six open and eight a second gives more than twice that without asking any faster than the
legacy parser did for years.

A rate of `0` removes the ceiling and leaves concurrency as the only limit. Keep the
ceiling: it is what protects a shop that suddenly starts answering in fifty milliseconds,
which concurrency alone does not.

**One process per run**, so a parser that leaks or wedges takes down its own process and
nothing else. `RUN_TIMEOUT_MINUTES` kills one that stopped answering; without it a hung
channel would hold its own live-run slot forever.

**The scheduler finishes a run its worker did not**, because it is the only thing that knows
the worker is gone. It never overwrites one that reported for itself: the attempt conflicts
and is dropped, so the worker's own reason survives — which is also why shutdown reaps
rather than closing everything as "scheduler stopped".

**`SCHEDULER_MAX_RUNNING` defaults to 1.** Two concurrent crawls on a small box is how the
memory limit gets found, and a channel collects far faster with a couple of neighbours than
with a dozen.

## The worker

One process per run, spawned by the scheduler, so a parser that leaks or wedges takes down
its own process and nothing else.

**It reaches the service over HTTP with its own credentials, not through the database.** A
parser is the one thing here that runs hostile input through itself all day, and what it
holds while doing that decides what a compromised one is worth. A worker token carries
`aud=worker` and reaches exactly five routes:

| | |
|---|---|
| `POST /api/worker/auth/login` · `POST /api/worker/auth/refresh` | its own session |
| `GET /api/worker/runs/{run_id}` | the job |
| `POST /api/worker/runs/{run_id}/finish` | report back |
| `POST /api/worker/sources/{source_id}/offers/batch` | hand over a pass |

`tests/test_worker.py` asserts that exact set, so a sixth route is a decision rather than
an accident.

**The job is asked for, not passed on the command line.** The channel's declaration travels
with the run — including which facts *this* pass is expected to bring back, already chosen
by the kind so a worker cannot pick the wrong list — which means a worker started by hand
gets the same answer as one the scheduler spawned.

**A handed-over pass writes no audit entry**, unlike the same call on the admin router. Not
an oversight: the trail records what an administrator did, and a scheduled crawl is not
that. What a run collected is recorded on the run, which is where somebody would look.

**A 401 mid-pass is retried once** through a fresh sign-in. A slow channel can outlive an
access token, and losing a completed crawl to an expiry would be absurd.

**The snapshot directory belongs to the image, not to the daemon.** Docker seeds a fresh
named volume from the directory in the image, so a mount point that exists and is owned by
the application user comes up writable; left to the daemon it is created root-owned and the
collector fails on every single product with a permission error. That is checked once now,
before the first request — `SnapshotStore.ensure_writable` — because discovered one product
at a time it reads as a shop that served 1400 broken cards, which is the wrong thing to go
and look at.

**A snapshot carries more than bytes.** The URL and, on a marketplace, which trader the
listing belonged to — facts the crawl had and the page does not state. Without them a
reparse of a marketplace channel would fail on every item for want of something it already
knew. The worker fills them from the listing, so a channel does not have to remember to.

## Channels

One module per source slug in `channels/`, registering itself on import. Adding a shop is
adding a module and a line in `channels/__init__.py`; nothing about the scheduler or the run
lifecycle changes.

| slug | shop | access | decode | products | deterministic |
|---|---|---|---|---|---|
| `ksenukai-phones` | ksenukai.lv | wholesale | private_api | 521 | 100% |
| `bigbox-phones` | bigbox.lv | wholesale | private_api | 985 | 93.1% |
| `bigbox-tablets` | bigbox.lv | wholesale | private_api | 537 | 98.5% placed |
| `ksenukai-tablets` | ksenukai.lv | wholesale | private_api | 229 | 99.1% placed |
| `onea-phones` | 1a.lv | wholesale | private_api | 443 | not measured |
| `onea-tablets` | 1a.lv | wholesale | private_api | 229 | 94.3% placed |
| `rdveikals-phones` | rdveikals.lv | retail | markup | 1396 | 99.8% |
| `rdveikals-tablets` | rdveikals.lv | retail | markup | 584 | 100% placed |
| `dateks-phones` | dateks.lv | retail | markup | 745 | not yet run |
| `dateks-tablets` | dateks.lv | retail | markup | 402 | 98.8% placed |
| `bm-phones` | bm.market | wholesale | graphql | 937 | not yet run |
| `bm-tablets` | bm.market | wholesale | graphql | 441 | not yet run |
| `euronics-phones` | euronics.lv | retail | json_ld | 319 | not yet run |
| `euronics-tablets` | euronics.lv | retail | json_ld | 122 | 100% placed |
| `cec-phones` | shop.cec.lv | wholesale | graphql | 92 | not yet run |
| `cec-tablets` | shop.cec.lv | wholesale | graphql | 160 | not yet run |
| `discover-phones` | discover.lv | wholesale | xml | 560 | not yet run |
| `discover-tablets` | discover.lv | wholesale | xml | 222 | not yet run |
| `tet-phones` | tet.lv | retail | markup | 319 | not yet run |
| `tet-tablets` | tet.lv | retail | markup | 210 | not yet run |

ksenukai and 1a share one lupasearch index; a category is one leaf name in it
(`Planšetdatori` for tablets), so their tablet channels are the phone class with another
leaf, not another module.

**A tablet filed among a shop's phones is left out at discovery**, through one shared check,
`channels/tablets.py`: the word in the feed's languages, `Wi-Fi + 4G`, and the makers'
tablet lines. m79 and bigbox need it — six tablets had become phone entries by 23.09.2026,
`Blackview Active 7 Wi-Fi + 4G 11` among them — and a channel that meets the same thing
calls the same function rather than growing a pattern of its own.

`rdveikals-phones` is the first that reads markup and the first with a cheap pass. Its own
module says why its discovery walks the listing rather than the sitemap, and why the brand
comes out of an analytics block instead of the microdata beside it.

**`tet-phones`** states more on its listing than any other channel here: every card
carries the price, the stock flag **and the manufacturer's code**, on 333 of 333. Six
requests of sixty are therefore a complete cheap pass, and the product page adds the one
thing the card has not got — `#i-product-data` states the barcode, on 98.1% of the 319
collected.

Three things its module records:

- **Page seven is not empty and not a repeat of page six.** It answers with sixty products
  the walk has already seen — the listing wraps round rather than ending — so the walk stops
  on a page that brings nothing new.
- **Fourteen refurbished phones sit in the same category and are left out.** `Apple iPhone
  12 64GB Black Pre-owned C grade [Refurbished]` costs 198 euro, and with nothing here
  distinguishing condition it would attach to the entry for a new one and show as its
  cheapest price. Same decision as cec's refurbished section.
- **Its JSON-LD says `InStock` for everything**, including what the shop itself flags
  `Drīzumā`. That is the fourth shop in a row, and it is now written down in
  `.claude/rules/reading.md` rather than in a fifth module docstring.

**`discover-phones`** is the cheapest channel here: `/catalog.xml` is the whole shop in one
request — 2768 products, 560 of them phones — with no key and no header. There is no listing
to page and no product page to open, and its ruleset reads the rest out of the name, which
is the tidiest of the nine: `BRAND MODEL CAPACITY COLOUR`, 560 of 560 yielding a model.

It has **no barcode and no part number anywhere** — not in the export, not on the page — so
everything it is worth rests on brand, model, capacity and colour. Three things its module
records: the product page is deliberately not opened (it adds a specification table nobody
reads, and is windows-1257 with no charset header); one section arrives as
`Mobilie telefoni >> <b>Apple`, with a bold tag that leaked out of the shop's own page; and
`in_stock` is `1` on all 560, which means the export holds what the shop will sell and a
product that leaves it has left the shop.

**`cec-phones`** is the smallest channel here and the most targeted: 92 iPhones from an
Apple Premium Reseller, in two requests. Apple is where this system is thinnest — bm.market
has 42 barcodes on its 196 Apple products — and this shop publishes **no barcode at all**,
which turns out not to matter: its `sku` is Apple's own code, and 89 of these 92 are already
here, carried by up to four other shops each.

- **The products are not the offers; their variants are.** All twelve items in the category
  are `ConfigurableProduct` and expand into the 92 phones a shopper can buy. Reading the
  twelve would file a whole family as one product.
- **The brand is supplied, because the shop states none.** Its schema has 41 fields on a
  product and not one is a maker. The category answers it, and the answer is checked rather
  than assumed: all 89 codes already here are published under Apple.
- **The refurbished section is deliberately left out.** Its four products are used phones,
  and nothing in this system distinguishes condition yet — `offers.condition` exists, every
  one of the 5442 listings is `new`, and matching and the storefront ignore it. A used
  iPhone 16 Pro would attach to the variant for a new one and show as its cheapest price.

**`euronics-phones`** is the best-stated source here and the one with the shortest
ruleset — one rule. Its product page states the brand, the part number, `gtin13` **and the
model** as JSON-LD, so generic finds all four without help: 100%, 100%, 100% and 99.7%. No
other shop here states a model at all.

**Discovery is one request.** The listing pages are cumulative and the `?f=` token that
selects one is a protobuf message whose sixth field is the page number, so a token built for
a page past the end returns the whole category at once — 319 phones in 2 MB, with the `Load
more` anchor gone. The token this builds for page 2 is byte for byte the shop's own, which
is what says the shape was read rather than guessed. Walking the pages in order, as the
previous parser did, downloads the same cards over and over.

Two things it would be read wrongly without, both measured on all 319:

- **`data-product-price` is not always the price.** On 51 of them the card leads with
  `Friends price` and keeps the real one in a `discount__old__loyal` block beside it: 599.99
  against 839.99. The comparable price is the old one where a loyalty discount is shown.
- **`data-product-brand` is `Vaikimisi`** — Estonian for "default" — on every card, so the
  brand comes off the product page and the placeholder is dropped rather than carried.

Its JSON-LD `availability` is a constant `InStock`, including on all 58 the listing itself
marks `On order`. That is the third shop in a row, after dateks and bm.market, whose
structured data means the shop will sell the thing rather than that it has it.

**`bm-phones`** is the first that reads GraphQL, and the cheapest channel here by a wide
margin: Magento 2 with `POST /graphql` open — no key, no signature — answering 200 products
with every attribute per request, so the whole category is 5 requests and 74 seconds and no
product page is ever opened. Three things its module records, each of which reports success
while being wrong:

- **The category is `Telefoni`, not `Mobilie telefoni`.** The second is the bigger of the
  two, 3448 against 937, and it is a section: its products include Apple Watches.
- **`stock_status` is a constant.** It reads `IN_STOCK` on 936 of 937 — Magento saying the
  shop will sell the thing. `availability_type` beside it says 934 are `Pēc pasūtījuma`.
  This is a showroom that orders in, and the first field would report a warehouse it has not
  got.
- **The brand is only in the selected options.** `manufacturer` is a Magento select, so
  `AttributeValue.value` is null on it and the label is in `AttributeSelectedOptions`. The
  obvious query loses the brand on all 937 and looks like it worked.

Half its catalogue carries the attribute block and half does not — 476 of 937 — which is
where its barcode (50.8%) and part number (45.8%) go. For Apple, the thinnest brand here at
42 barcodes on 196 products, the part number is not missing from the page but written into
the name, and reading it there takes Apple from 41 to 161.

**`dateks-phones`** is the cheapest cheap pass here: the listing prints the name, both
prices, the manufacturer code and a stock word on 100% of 745 cards, so 32 requests bring
back the whole category's prices and stock with no product page opened. Its module records
what a reader of this shop would otherwise get wrong, and three of those are worth naming
here because they are the kind of mistake that reports success:

- **The category moved and the old address still answers 200.** `/cenas/mobilie-telefoni`
  serves a section page full of navigation and no products. A channel pinned to it would
  report an open, empty shop — so `discover` raises on a first page with no cards rather
  than returning none.
- **The page number in the address is one less than the page**, so a walk that starts at
  `/pg/1` quietly drops the first 24 products.
- **The page's own schema.org `availability` reads `InStock` for everything**, including
  the 513 of 745 the shop itself calls `Pasūtāms`. The words are read; the claim is not.

They share 207 barcodes, which is the first thing in this system there has ever been
anything to match against — and close to what the old corpus showed, where 39.5% of
barcodes appeared in more than one shop.

**`ksenukai-phones`** reads the shop's own search index. The site is behind Cloudflare —
catalogue pages answer with a challenge and its API is disallowed — so there are no product
pages and no images for a robot, and everything usable is in the third-party index its front
end queries. A few requests return the whole category, which is what `wholesale` means: no
listing-then-card split, and therefore no cheap pass, which the source's constraints already
refuse to let anyone configure. `fetch` is a no-op that writes the record into a snapshot, so
a re-read works exactly as it does for a shop whose cards are fetched one at a time.

Two things it taught us, both found by measuring rather than by reading code:

- **The model is only in the encoded columns.** The index keeps attributes in two places —
  an `attributes` list with five names and units, and `attributes_lv_*` columns whose name is
  base64 inside the field key. Ten names live only in the columns, and one of them is
  `Modelis`, on 100% of products. Reading only the list, as the first attempt did, threw away
  the one field brand-and-model matching stands on.
- **A repeated name is not a duplicate.** About a third of these products list
  `Aizmugurējā kamera` more than once; keeping the last would quietly drop half of what the
  shop said about their cameras. The values are joined instead.

**`bigbox-phones`** is the same third-party index behind a different key, which was not
the plan — it was picked to prove a different decode path and turned out to be the same
one. Its site is a Next.js application with an empty listing in the HTML and product pages
behind a rate limit that answers 429 after roughly one request a second, with no
`Retry-After` to read. Opening them is also unnecessary: the index carries what the
specification table carries, and the one thing only a page holds is a description, which
takes no part in matching.

Its attributes are numbered rather than named — `attribute_string_466` is internal storage
and nothing in the record says so. The index labels the filterable ones in its facets,
which are fetched once per pass and **written into every snapshot**: a snapshot that needed
a second document to be readable would not be a snapshot. The rest keep the key the shop
gave them, because an invented name would be our vocabulary wearing theirs.

**The barcode is handed over untouched.** `alternative_codes` mixes barcodes with the shop's
internal numbering, and picking between them is a reading decision — check digits and
reserved prefixes are a standard, not something this shop invented. A parser that chose here
would bake one interpretation into the only copy of the bytes there is, and every other
channel would then make the same decision separately and differently.

## Not built yet

**Nothing reads the shop's shape into ours.** `generic-1` finds a title, a brand and a price
in what this channel hands over and nothing else, so a real pass of 520 phones lands with no
barcode, no part number and no model. That is the designed order — collect, measure, then
write the rules against the bytes rather than against a guess — and the coverage on the run
says it out loud.
