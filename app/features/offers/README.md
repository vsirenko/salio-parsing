# offers

Taking in what a shop served, keeping it verbatim, and reading it.

This is the only place in the system where bytes from outside are stored as they arrived.
Everything downstream is derived from them and can be thrown away.

## Endpoints

| | |
|---|---|
| `POST /api/admin/sources/{source_id}/offers` | submit one observation |
| `POST /api/admin/sources/{source_id}/offers/batch` | submit many, gzipped |
| `GET /api/admin/offers` | the listings — by shop, entry (`variant_id`), family (`product_id`), condition, `listed`, `match_state`, `queue_reason`, `method`, `availability`, `brand_id`, `category_id`, price range, `search`; sorted by price, first or last seen, shop, title |
| `GET /api/admin/offers/coverage` | how far a deterministic matcher could get |
| `GET /api/admin/offers/unresolved-colours` | what shops write for a colour that did not become one, and why |
| `GET /api/admin/offers/{offer_id}` | one listing |
| `GET /api/admin/offers/{offer_id}/raw` | every observation of it |
| `GET /api/admin/offers/{offer_id}/trace` | its path from the shop's bytes to the catalogue: the reading recomputed rule by rule, the match, the entry |
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

**A listing row names its shop and seller and says where it is placed** — `shop`, `seller`,
`placed_on: {variant_id, variant_title, method}` — and whether the shop still has it,
`listed`: seen by its channel's newest full pass that ended ok (`offer_is_listed` in
`app/db/query.py`, the pipeline's rule). A product card asks
`product_id=…&listed=true&condition=new&sort=price`: who sells the thing new today,
cheapest first. The placement is read from `offer_matches`, which is `matching`'s table;
reading it is not a cross-feature import.

**A row is named, and says where the matcher left it.** `title`, `brand_raw` and `gtin` are
the shop's own, from the newest reading of a pass that carried the catalogue; `brand` and
`category` are ours — the placed product's, and for a listing not placed the category its
channel collects (it has no brand of ours: resolving one is what failed). `match_state` is
`placed` (an active match), `queued` (a `match_queue` row, with its `queue_reason` — the
ambiguous ones are `queued` with `ambiguous`, `brand_ambiguous` or `low_confidence`) or
`unplaced`, neither: a refurbished or used listing the matcher leaves out, or one only a
quick pass has seen. Review asks `match_state=queued&queue_reason=ambiguous`, or
`method=brand_model` for the placements resting on a model name alone. `search` is a
fragment of the title or the shop's id, or a whole barcode, compared padded to fourteen
digits as it is stored — a fragment of a barcode names nothing.

**What the registry does not know is computed, not queued.** `unresolved-colours` takes
every listing whose current reading has a colour field and no colour, resolves its fields
again with the category rule's own function (`devices._canonical`) against the registry as
it is now, and says why each did not become a colour: `unknown` — a word to enter; `pair` —
known colours whose combination is not a value, which an alias must not paper over;
`conflict` — fields naming different colours, which the reading rightly refuses and no row
fixes; `resolves_now` — a reading older than the registry, which a reparse fills. It stores
nothing and so cannot go stale; the one thing kept is a word marked as none of the colours
(`attribute_value_dismissals`, in `attributes`). On 24.09.2026 it was 105 listings: `Black`
at dateks was never a language problem, it sat beside `zils` in a second field.

**What a reading found is filterable on the list** — `source_id` (a channel that observed
it), `has_gtin`, `has_model`, `has_all_axes` (every axis its category names identity-bearing),
`missing_axis=color` — the same tests the pipeline's read node counts by, so a node leads to
exactly the listings behind its number. `model` and the canonical `identity` are copied onto
the offer for it, beside the title.

**Those names are copied onto `offers`, like the price.** Picked out of the observations per
row, a page sorted by title took 0.4 s over 18660 listings, before counting its total. They
are written wherever a reading is applied to its offer, and **not by a quick pass**: it
carries a price and a stock flag, no title and no barcode, and taken as current it would
blank both — the matcher passes over it for the same reason (`MatchingService._reading`).
A listing only ever seen by a quick pass therefore has no title, which is true: nobody has
read its card. And only from the listing's **newest** such observation, the order
the matcher and the pipeline read by: re-reading an older one used to put its reading over
the newer one's, and 18 tablets carried the axes of the observation before theirs. No picture yet: nothing reads one out of a payload, and the shops write it
five ways (relative paths, icons in the list) — see `TODO.md`.

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

**Normalization is a pure function of the payload and the rules that apply to it.** That is
the property the whole pipeline is built for: improving a rule means re-running it over what
is already stored and comparing the old reading with the new one before accepting it.
Re-running the same version is idempotent; a new version gets its own row, so both readings
exist side by side.

## Reading in layers

Rules are declared objects, not a chain of conditionals, so the set an offer will get can be
read **before** any of them has run — a chain answers that question only by being executed,
and then only for the offer you happened to try. `rules_for(...)` is that answer.

Six layers, general to specific, each seeing what the ones before it tidied. What changes
down the list is not only how specific the knowledge is but **what selects it**:

| layer | selected by | reads |
|---|---|---|
| `GENERIC` | nothing | any flat object: conventional key names, a comma decimal, a barcode shape |
| `CATEGORY` | the category | what this kind of product means |
| `SHOP` | the shop | what its codes and stock words mean, in every category it sells |
| `SOURCE` | the channel | how it names this category's products |
| `BRAND` | (category, brand) | this maker's conventions |
| `PRODUCT` | (category, brand, line) | one line's own habits |
| `FINISH` | nothing | check digits, reserved prefixes, canon |

Four things that ordering encodes:

- **The category comes before the shop.** The same shape of value means different things to
  a laptop and a monitor — `128 GB` is an identity axis for one and a footnote for the other
  — and keeping their rules in one list means applying the wrong one eventually.
- **The shop comes before the channel.** Barcodes, part numbers and stock words mean the
  same whichever of a shop's categories a listing is in; how it names a product may not. They
  were filed under the channel until 23.09.2026, which would have read a second category of
  the same shop without any of them. Split then, 16 rules out of 11 channels, and re-read
  over 9013 listings with no field of any reading moving. cec's one rule stayed: it supplies
  `Apple` because the shop's category is `iPhone`, which is a fact about the channel.
- **The shop comes before the brand**, because a brand knows more about its own product than
  any shop does and should see a string the shop's rules have already tidied.
- **A brand is scoped to a category, not global.** `phones/apple` and `laptops/apple` are
  different rulesets: that a part number looks like `XXXXXYY/A` is true of Apple everywhere,
  that a screen diagonal is part of the name is true only of a MacBook Pro.

`PRODUCT` is selected from what the layers above produced, which is why it runs last before
canonicalisation: a line cannot be known until the brand and the model have been read. A rule
names one by writing `_line`, and every key beginning with an underscore is working state
that `read` drops before anything is stored.

**The version says what was applied**: `generic-1+phones-1+ksenukai-1`, composed rather than
opaque, so a row can be attributed without looking anything up. A key with no ruleset is read
by whatever is more general, which is how a sample gets loaded and measured before any rules
are written for it.

**Words a rule needs come in as a `Vocabulary`, never out of a query.** Reading is a pure
function of a payload and the rules that apply to it — that is what lets a stored payload be
read again and the two readings compared — and a rule that went to the database for a word
would make the answer depend on when it was asked. So `OfferService` loads the words once per
category and hands them to `read()`. Empty is valid: a rule given no words does nothing,
which is a rule declining to guess rather than a rule that is broken.

The first of those words is what a shop calls the category, which is how bigbox's model is
read (see [categories](../categories/README.md)). They are Latvian here and Lithuanian one
shop later, so they are rows — a tuple in this module would be a code change per country.

The last of them is what a maker calls what it makes, and **the model is the registry's
spelling, found whole in the title.** Two shops publish no model field; their rules cut the
model out of the title by subtraction — everything before the first capacity — and what the
shop wrote in between stayed on, so 211 of 1524 catalogue entries were named
`Galaxy S26 S942 5G Dual Sim`. The last rule of the category reads the title again and
takes the longest name the registry knows: whole words, longest wins, two different names
decide nothing. Measured before it was written, a known name sits whole in 77% of bm's
titles and 88% of m79's, where their own rules agreed with the rest of the market on 21%
and 26%. A title holding no known name keeps what the shop's rule read — and so does one
that carries a known name on with a variant word (`Pro`, `Max`, `Ultra`, `Plus`, `Fold`,
`FE`…): `iPhone 16` inside `iPhone 16 Pro` is the sibling, and before this was checked the
registry, knowing only the shorter name, filed 21 listings under the neighbouring phone. A
gap in the registry has to read as a gap. For the same reason a stated maker the catalogue
knows but the registry has no page for reads nothing from it, where it used to read every
maker's page: ZTE has none, Hammer's holds `Blade`, and four ZTE phones were one entry. A
brand field naming no maker we know (`Nothing Phone`, a reseller) still opens every page.
Laptops read through the same rule since `laptops-8`, for a different reason: their
subtraction is clean, but a maker's name comes in more than one word order — Dell's
`Pro 14 Essential` 78 times beside `Pro Essential 14` 17, `16 Plus` beside `Plus 16` — and
only a row can say which order is the maker's. So far only Dell has laptop rows, entered as a
complete line: an entry for `14 Plus` alone would be the longest name found in
`Inspiron 14 Plus`. A laptop line with a model number in it (`XPS 14 9440`, a 2024 machine,
beside the 2026 `XPS 14`) is entered with the number, so the longer name keeps them apart.
The registry
itself — where it came from, why it is per brand, why `+` survives — is described in
[brands](../brands/README.md), "The model registry".

**A brand lives inside a category**, which is why the tree nests
`normalization/brands/phones/apple.py`. A module there is mostly the measurement that
justifies its rules, as the first two are: Apple's part number is five characters of
configuration, two of market and `/A`, and nine of ninety-six configurations in the
collected corpus are split across market codes — nine phones that look like eighteen.
Samsung's looks the same and behaves nothing like it: its trailing letters carry the colour,
which tells two phones apart, so cutting them the way Apple's allow would merge phones that
really are different.

**A rule may be declared and not written.** `Rule.pending` is a gap that is visible, and the
first one is real: colour splits a phone into variants, and across 520 collected products the
word before `krās` takes 61 distinct forms — Latvian declension (`melns`, `melna`), plain
English (`black`), and the maker's own marketing (`obsidian`, `glacier`). Two of those three
are not a category's business, and a colour canonicalised wrongly splits one product into
several, confidently.

**`identity` is where canonical attributes go**, apart from `attributes`, which holds the
shop's own names untouched. Mixing our vocabulary into theirs would leave no way to tell
which is which, and this is what an identity key is computed from.

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
- **The generic layer is not a placeholder.** It reads a flat object with conventional keys,
  handles a comma decimal separator and a currency written into the price string, and refuses
  a barcode that is not 8–14 digits — a `gtin` field holding "n/a" would otherwise put
  nonsense on the strongest signal the matcher has. On a shop with no rules of its own it is
  the whole reading, and the coverage on that shop's run is what says which rules to write.
- **Rules are written against collected bytes, never against a guess.** Every `why` in
  `normalization/` names the case from the data that put it there. The order is deliberate:
  collect, measure, then write. On ksenukai's 520 phones the layers read
  `gtin 0% → 99.6%`, `model 0% → 100%`, `storage 0% → 97.9%`, and `mpn` stays 0 on purpose —
  its article numbers all begin `Y0000` and can never agree with another shop's.
- **Choosing a barcode is a reading decision, not a parser's.** Check digits and GS1's
  reserved prefixes are a standard, so `normalization/barcodes.py` owns it: a channel hands
  over whatever the shop called its codes, and one place decides which is real.
- **A barcode has one form: a zero-padded GTIN-14.** A UPC-A and the EAN-13 it becomes with
  a leading zero are one code, and stored as written they were two: 229 of 2736 codes were
  read both ways, and the barcode rung missed between the shops that wrote them
  differently. `barcodes.canonical` pads every code a reading keeps, the catalogue pads one
  typed in by hand, and `variant_gtins` refuses anything but fourteen digits. A channel
  still hands the shop's own digits over untouched — the padding is a reading decision.
- **A source names its category** (`sources.category_id`, nullable). It is what selects the
  category's rules. Null means a channel carrying a whole shop, and then those rules simply
  do not apply — honest rather than a gap, because reading a monitor by a phone's rules is a
  confident wrong answer and no rules at all is only a quiet one.
- **An unchanged payload still gets read again when the rules have moved on.** Ingestion
  short-circuits on identical bytes — that is what keeps `raw_offers` proportional to how
  much the world changes — and a reparse goes through the same path. So a shop that had just
  gained a rule kept the reading it had from before anybody wrote one, and the rule looked
  like it did nothing. The stored `ruleset_version` is now compared before the short circuit
  is trusted, and a row is written only when it differs; a pass that changed nothing still
  writes nothing.
- **A reading from a cheap pass is a price, not an identity.** `delivers_quick` is a
  declaration that a pass carries the price and the stock flag and nothing else, so its
  reading has no barcode, no part number and no model. Taken as the current reading it
  erases what the expensive pass collected: a shop went from 1393 of 1396 products carrying
  a barcode to none, and every one of them stopped matching, because a two-minute price
  refresh had run after the four-minute catalogue pass. Whatever asks "what is this listing"
  — the matcher, and the tool that draws the queue — reads the newest reading **from a pass
  that carried the catalogue**. The price is not lost by passing over it: it is on the offer
  row, and updating that row is what the cheap pass is for.
- **A rule body that changes without its version changing is a fix that reaches nothing.**
  The version is what a re-read compares to decide whether a stored reading is stale, so
  editing a rule and leaving `phones-2` alone means the reparse keeps every row and the rule
  looks broken. This cost three rounds of confusion in one afternoon, so
  `tests/test_normalization_layers.py` fingerprints each ruleset's code — bodies, helpers,
  regexes and bounds, but not prose — and fails naming the ruleset whose version has to go
  up. Bump the version and the fingerprint in the same commit.
- **Payload keys in the ruleset must be written in lower case**, and an assertion at import
  enforces it. They are matched against a lowered payload, so a key with a capital never
  matches anything — which is what silently happened to `currencyId`.

See also `docs/parser-design.md`, "Raw is kept; everything after it is recomputable".
