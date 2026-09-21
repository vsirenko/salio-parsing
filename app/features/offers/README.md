# offers

Taking in what a shop served, keeping it verbatim, and reading it.

This is the only place in the system where bytes from outside are stored as they arrived.
Everything downstream is derived from them and can be thrown away.

## Endpoints

| | |
|---|---|
| `POST /api/admin/sources/{source_id}/offers` | submit one observation |
| `POST /api/admin/sources/{source_id}/offers/batch` | submit many, gzipped |
| `GET /api/admin/offers` | the listings — filter by `seller_id`, `market_code` |
| `GET /api/admin/offers/coverage` | how far a deterministic matcher could get |
| `GET /api/admin/offers/{offer_id}` | one listing |
| `GET /api/admin/offers/{offer_id}/raw` | every observation of it |
| `GET /api/admin/raw-offers/{raw_offer_id}/reading` | our reading of one observation |
| `POST /api/admin/raw-offers/{raw_offer_id}/renormalize` | read the stored bytes again |

Ingestion is a POST because there is no fetcher yet, and that is the point rather than a
placeholder: a sample can be loaded by hand and measured before a line of crawling exists,
and the measurement decides what the matcher should be.

## Ingesting in batches

A pass over a nine-hundred-product shop is, one at a time, nine hundred requests, nine
hundred transactions and nine hundred audit entries. The last is the real objection: the
trail exists to show what an administrator did, and a crawl would bury that under a wall of
"an offer arrived". A batch is one request, one transaction and **one** audit entry, whose
changes carry the numbers that matter — how many arrived, how many were accepted, how many
failed, and which run brought them.

**Post it gzipped.** `Content-Encoding: gzip` on the request is decompressed by
`app/core/compression.py`, because Starlette compresses responses and does not decompress
requests. Product JSON compresses by roughly an order of magnitude and the difference is
paid on every pass of every channel. Expansion is capped as it happens, not checked
afterwards: a few kilobytes of gzip expand to gigabytes of zeros, so an uncapped
decompressor turns any endpoint taking a body into a way to exhaust the machine from
outside.

**Partial on purpose.** One malformed card does not throw away the pass that collected the
other eight hundred and ninety-nine — exactly the case `runs.items_failed` exists to
record. Each item is written inside a savepoint, so a failure undoes that item and leaves
the batch standing; a plain flush would abort the whole transaction on the first bad row.
Failures come back **named**, because a batch reporting "two failed" is a batch nobody can
fix.

**The market is on the batch, not on each item.** Every observation in one pass comes from
one channel showing one market, and repeating it per item only invites them to disagree.

**`run_id` is carried through to `raw_offers`.** Null when a sample is loaded by hand. It
earns its column because when a run is rejected, or its coverage falls off a cliff, the
question is always "show me what that run actually saw" — and a timestamp narrows that to a
window rather than to a set of rows. `SET NULL` on delete: the observations are facts about
a shop, and the run is only how they arrived.

The single-observation endpoint stays. It is what a person uses to check one card by hand.

## How it works

**Four levels, not two.**

```
raw_offer          bytes as the shop served them, at one moment   observation
normalized_offer   our reading of those bytes                     versioned, recomputable
offer              the listing's identity between crawls          "this is the same listing"
variant            the thing being sold                           our conclusion
```

**`offer` is separate from `raw_offer` on purpose.** The listing persists across fetches and
the raw rows are observations of it. Merge them and every crawl produces a new offer, so the
match has to be made again from nothing each time and the price history restarts with it.

**One raw row per distinct content, not per fetch.** The payload is hashed with sorted keys —
a source that reorders its JSON has not changed — and an unchanged page bumps `last_seen_at`
and writes nothing. `stored: false` in the response says so. That keeps this table
proportional to how much the world changes rather than to how often we look at it.

**Normalization is a pure function of the payload and the ruleset version.** That is the
property the whole pipeline is built for: improving a rule means re-running it over what is
already stored and comparing the old reading with the new one before accepting it. Re-running
the same version is idempotent; a new version gets its own row, so both readings exist side
by side.

**Brand and category arrive as strings.** `brand_raw` and `category_raw` hold what the source
wrote; resolving them to rows is matching's work, not normalization's. The unresolved string
is also what a candidate queue would be filled from.

## Decisions worth knowing before changing it

- **A marketplace offer has to say which seller it belongs to.** Price history is keyed by
  seller; without one, a listing's prices would be drawn through every trader on the
  platform at once. An ordinary shop has exactly one seller and does not need to say.
- **A trader is created by ingestion**, not entered ahead of it — on a marketplace they
  arrive in the data. On a non-marketplace the seller already exists, created with the shop.
- **Ingestion does not check `shop_markets`.** That flag controls where offers are *shown*;
  collection happens regardless, so a market can be filled with data before it is opened.
- **The price on `offer` is the latest reading**, derived and recomputable. It is kept only
  so a card does not have to walk the observations to show a number; the record of what a
  price ever was belongs to the readings, and later to `price_event`.
- **The generic ruleset is a placeholder with a real job.** It reads a flat object with
  conventional keys, handles a comma decimal separator and a currency written into the price
  string, and refuses a barcode that is not 8–14 digits — a `gtin` field holding "n/a" would
  otherwise put nonsense on the strongest signal the matcher has. Per-source rulesets come
  with the fetchers.
- **Payload keys in the ruleset must be written in lower case**, and an assertion at import
  enforces it. They are matched against a lowered payload, so a key with a capital never
  matches anything — which is what silently happened to `currencyId`.

See also `docs/parser-design.md`, "Raw is kept; everything after it is recomputable".
