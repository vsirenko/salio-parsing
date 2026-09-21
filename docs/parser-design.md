# Parser design

Draft. None of this is built yet. It is the shape to build against, and — at the end —
the questions that have to be settled against real data before any of it is worth
writing.

## What is being built

Listings from many shops, turned into one catalogue: a buyer sees one product with every
seller's price next to it, and how those prices moved over time.

The hard part is not fetching. It is deciding that two listings, written by two shops
that have never agreed on anything, describe the same thing.

## What this has to work against

| | |
|---|---|
| Sources | Mixed — official feeds and APIs, plus HTML scraping |
| Catalogue | Mixed — no single set of variant axes across categories |
| Scale | Hundreds of thousands to millions of offers |
| Hard pairs | Decided by an LLM judge |

Each of those removes an easy answer:

- **Mixed sources** mean a barcode is there sometimes, not always. The matcher cannot be
  built around one.
- **A mixed catalogue** means the attributes that separate one variant from another
  differ per category, so they cannot be table columns.
- **The scale** means the judge cannot be a stage every offer passes through. At a
  million offers, even five per cent unresolved is fifty thousand calls per pass.

## Pipeline

```
SOURCE
  ↓  FETCH                 skip unchanged pages: content hash, ETag, Last-Modified
  ↓  RAW PARSE
RAW OFFER                  an immutable fact from the shop, kept verbatim
  ↓  NORMALIZATION         a pure function of (raw payload, ruleset version)
NORMALIZED OFFER           our reading of that fact, recomputable at any time
  ↓  IDENTITY EXTRACTION   barcode, brand + part number, model string, title
  ↓  CANDIDATE GENERATION  an index lookup, never a scan
  ↓  DETERMINISTIC MATCHER
  ↓  unresolved only
  ↓  LLM JUDGE             cached by pair; its verdicts feed back into the rules
  ↓  DECISION POLICY       when unsure, do not link
PRODUCT / VARIANT LINK
  ↓
PRICE HISTORY + SEARCH INDEX
```

The arrows read as one pass, but the pipeline is re-entrant on purpose: normalization
and everything after it must be re-runnable over stored raw data without going back to
the network. That is not a convenience. Matching rules get rewritten hundreds of times,
and each rewrite is worth only what it costs to re-apply to the corpus already held.

## Principles

### Raw is kept; everything after it is recomputable

`raw_offer` stores the bytes the shop served, not fields picked out of them. Storage is
cheap, re-crawling is not, and a field nobody thought to extract in month one is the
field the matcher needs in month four.

Everything downstream is derived and disposable. Losing the normalized table costs a
recompute; losing the raw table costs a re-crawl of the whole corpus.

### Some attributes carry identity, most do not

In a mixed catalogue the variant axes are data, not schema. Each attribute definition
carries a flag: does changing it make this a different thing to buy?

- 256 GB instead of 128 GB — different variant.
- Size 42 instead of 40 — different variant.
- A different photo angle, a longer description, a seller's own blurb — same variant.

Without that flag the catalogue fails in one of two ways: distinct products collapse into
one, or every wording difference spawns a variant.

The same flag settles the product/variant question. **The variant is the primary
entity** — the thing that is bought, that carries a barcode, that an offer attaches to.
A product is a grouping for humans, and it is allowed to contain exactly one variant.
Do not invent a hierarchy where the category has none.

Offers attach to variants, never to products. An offer linked at product level puts the
price of a 128 GB phone in the same history as the 1 TB one.

### A match is an opinion, not a fact

The link between an offer and a variant is a row of its own, carrying the method that
produced it, the confidence, the evidence, who decided and when it was superseded — not
a `variant_id` column on the offer.

A column cannot be re-derived without destroying what it replaced, cannot be overridden
by a human without losing the machine's reasoning, and cannot explain itself when the
link turns out to be wrong. All three of those are needed on day one.

### Not linking beats linking wrongly

The two mistakes are not equal.

An unlinked offer is a hole: a product did not show up, and nobody was told anything
untrue. A wrongly linked offer is a lie: the buyer sees a price that belongs to a
different thing, and the price history takes a step that cannot later be told apart from
a real one.

So the decision policy is asymmetric. Below the confidence threshold, the offer stays
unresolved and goes to a queue. **A queue is a normal operating state, not a failure.**

### The judge's verdicts have to become rules

A pair cache stops the same comparison being paid for twice. That is necessary and not
sufficient — it only ever saves the repeat of an identical pair.

The economics come from the feedback loop. When the judge decides that
`Samsung Electronics Co., Ltd.` and `Samsung` are one brand, that belongs in the brand
aliases, and the next hundred thousand offers carrying that string never reach the judge
at all. The same goes for unit spellings, model-number formats and packaging noise.

Without the loop the expensive layer grows with the catalogue. With it, the layer
shrinks while the catalogue grows, which is the only version of this that stays
affordable.

### Barcodes are evidence, not proof

Sellers reuse barcodes across variants, inherit them from a supplier's wrong feed, and
occasionally invent them. A barcode match is the strongest single signal available and
still gets a sanity check: if the barcode agrees and the brand does not, that is a
conflict to record, not a match to make.

## Data model

Every table is written out under [The full shape](#the-full-shape); this is what the
groups are for.

**Taxonomy** decides what identity even means: the category tree, which attributes a
category has, and which of those attributes make one variant different from another.

**Catalogue** is what identity produces: brands, products, variants, and the merge trails
that let a wrong answer be corrected without destroying what it replaced.

**Commerce** is what flows through the pipeline: sources, sellers, listings, the raw bytes
behind them, the matches linking them to variants, and the price history that falls out.

Two of those tables carry most of the weight and are easy to get wrong.

**`offer_match` is a row, not a column.** Re-matching inserts and supersedes rather than
overwrites, so a bad rule can be rolled back and a human override survives the next pass.
A `variant_id` column on the offer would read faster and would quietly destroy the
previous answer every time the matcher ran.

**`price_event` records changes, not snapshots.** Daily snapshots of a million offers are
roughly 365 million rows a year; recording only the moves is smaller by more than an
order of magnitude. Partition by month from the first migration — introducing
partitioning to a live table of that size later is its own project. Seller, condition and
currency are all in the row from the start, because adding any of them afterwards means
migrating the largest table in the system.

## Product model

The catalogue is inferred, not authored. Nobody sits down and enters a product: one
appears because an offer arrived that matched nothing, and it is refined as more offers
arrive. That single fact drives most of what follows.

### The two levels, and why both

| | Answers | Needs |
|---|---|---|
| `product` | "show me phones like this one" | the family — every colour and capacity together |
| `variant` | "what does this exact thing cost, and where" | the buyable unit — one capacity, one colour |

Price comparison and price history need the variant. Search results and grouping need
the product. Neither level can do both jobs, which is why there are two.

`variant.product_id` is nullable. A variant that has just been created from an unmatched
offer does not yet belong to a family, and forcing one at creation would mean inventing
a grouping from a single data point. Grouping is a later, cheaper decision.

### Merge and split are first-class

A catalogue built from offers gets identity wrong and then learns better. Both
directions happen:

- two variants turn out to be the same thing — **merge**;
- one variant turns out to have been two — **split**.

So a variant id has to survive being merged away. `variant_merge` keeps the redirect:
the old id still resolves, price history stays attached to the surviving variant, and an
external link does not rot. Without it, a merge is a destructive operation on the one
table nothing else can be rebuilt from.

The same applies to products, at lower stakes — regrouping is mostly moving
`variant.product_id`, plus a redirect so a public URL keeps working.

### Identity key: the fast path

A variant carries a derived key over brand, normalized model and the values of the
identity-bearing attributes for its category. Two offers that produce the same key are
the same variant, with no matcher and no judge involved — a hash lookup.

The rule that makes it safe: **the key is only computed when every identity-bearing
attribute for the category has a value.** If colour could not be extracted, the key stays
null and the variant goes down the normal matching path. Without that rule, two different
variants that are both missing an attribute collapse into one — the exact failure the key
was meant to prevent.

Key set, key unique. Key null, matcher decides.

### What is not a variant axis

**Condition.** New, used and refurbished are the same variant. Their prices are not
comparable, so condition belongs to the offer and price history is keyed by
`(variant, seller, condition)`. Making it a variant axis triples the catalogue and puts
three cards for one phone in the search results.

Used stock is a side stream, not part of the main product. The headline price on a card
is the cheapest **new** offer; used never enters that number, or the card lies about what
the buyer gets. Used offers are collected and may be shown in their own block, and they
get no price chart — a used listing is one specific worn item that appears once and
disappears, so a line drawn through those points describes nothing.

Condition goes into the price history key from the first migration even though little is
built on it yet. That is what keeps the decision reversible: investing in used later
becomes storefront work rather than a migration of the largest table in the system.

Refurbished grades ("as new", "good", "acceptable") are kept as the source wrote them,
next to a canonical three-value condition. Grades are not comparable between shops, so
normalizing them would invent a precision that is not there.

**Seller packaging, photos, description length, the seller's own title.** All
descriptive. If it does not change what arrives in the box, it does not make a variant.

### What is a variant, awkwardly

Both of the following are their own variant. They are not the same problem, and one
`kind` column treating them alike is the mistake to avoid.

**A multipack** is N of one thing. `unit_count` describes it completely, a per-unit price
is computable, and once divided it competes honestly with the single item.

**A bundle** is different things sold together — a phone with a case and a charger.
`unit_count` says nothing about it; understanding its price needs to know what is in it,
which is what `variant_component` is for.

A bundle stays **out of the single item's price comparison**. Listing it as the cheapest
phone would be a lie, because the buyer is also paying for a case. It is its own variant,
it is found by search, and it does not enter the headline price.

Decomposing bundles is not attempted at first. Every component has to be matched in turn,
and component names inside a bundle title are described worse than ordinary offers.
Marking a variant as a bundle is cheap and enough; linking components is done later and
only where they are obvious.

### The full shape

Three groups. The taxonomy and the catalogue are what identity is decided against; the
commerce side is what flows through the pipeline into them.

```
-- Taxonomy -------------------------------------------------------------------

category              id, parent_id NULL, slug UNIQUE, name,
                      is_visible,                  -- what an operator sets
                      is_visible_effective,        -- own AND every ancestor; recomputed
                      identity_ready               -- attributes defined, extraction wired

attribute_def         id, category_id, key, name,
                      value_type(enum|number|bool|text),
                      unit_dimension(mass|volume|length|count) NULL,
                      identity_bearing             -- the variant axes
                      UNIQUE (category_id, key)

attribute_value       id, attribute_def_id, canonical, position
attribute_value_alias attribute_value_id, alias, origin(rule|judge|human)
                                                   -- "Natural Titanium" = "Titan Natur"

source_category_map   source_id, source_path, category_id, mapped_by, mapped_at
                      UNIQUE (source_id, source_path)   -- unmapped rows are the queue

-- Catalogue ------------------------------------------------------------------

brand                 id, canonical_name, slug UNIQUE
brand_alias           id, brand_id, alias UNIQUE, origin(rule|judge|human), confidence
                                                   -- where the judge's verdicts land

product               id, brand_id, category_id, title, is_visible
product_merge         from_id, into_id, merged_at, reason, decided_by

variant               id,
                      product_id NULL,             -- ungrouped until it is grouped
                      brand_id, category_id, title,
                      kind(single|multipack|bundle), unit_count,
                      identity_attrs JSONB,        -- base units: 500 g and 0.5 kg agree
                      identity_key NULL UNIQUE     -- only when every axis is extracted
                      CHECK ((kind = 'multipack') = (unit_count > 1))

variant_gtin          variant_id, gtin, origin, first_seen_at
                      PK (variant_id, gtin), INDEX (gtin)     -- the exact-match lookup
variant_mpn           variant_id, brand_id, mpn_normalized, origin, first_seen_at
                      INDEX (brand_id, mpn_normalized)        -- brand denormalized on
                                                              -- purpose: the block is
                                                              -- the pair, not the mpn
variant_merge         from_id, into_id, merged_at, reason, decided_by
variant_component     bundle_id, component_variant_id, qty    -- only when kind = bundle

-- Commerce -------------------------------------------------------------------

source                id, slug, name, kind(feed|api|scrape), trust(high|medium|low),
                      base_url, is_enabled

seller                id, source_id, external_id, name,
                      country,                     -- ISO 3166-1 alpha-2: VAT and
                                                   -- delivery differ across the EU
                      UNIQUE (source_id, external_id)

offer                 id, seller_id, external_id, url,
                      condition(new|refurbished|used), condition_grade NULL,
                      price, currency,             -- as the buyer sees it, VAT included
                      availability(in_stock|out_of_stock|preorder|unknown),
                      first_seen_at, last_seen_at
                      UNIQUE (seller_id, external_id)
                                                   -- the listing's stable identity;
                                                   -- price here is the latest reading,
                                                   -- derived and recomputable
raw_offer             id, offer_id, payload, content_hash, fetched_at, last_seen_at
                      UNIQUE (offer_id, content_hash)   -- one row per distinct content
normalized_offer      id, raw_offer_id, ruleset_version,
                      title, brand_id NULL, category_id NULL,
                      gtin NULL, mpn NULL, model NULL,
                      attributes JSONB, price, currency, condition

offer_match           id, offer_id, variant_id, method, confidence, evidence JSONB,
                      decided_at, decided_by, superseded_at NULL
                      UNIQUE (offer_id) WHERE superseded_at IS NULL
                                                   -- the match belongs to the listing,
                                                   -- not to one observation of it

price_event           id, variant_id, seller_id, condition, price, currency, at
                      PARTITION BY RANGE (at)      -- monthly, from the first migration
                      INDEX (variant_id, condition, at DESC)

judge_verdict         pair_fingerprint UNIQUE, verdict, reason, model, decided_at
```

Three things in there are decisions rather than plumbing:

**There is no `variant_id` on `offer`.** The active match is the row in `offer_match`
whose `superseded_at` is null, held to one by a partial unique index. A column would be
faster to read and would quietly destroy the previous answer on every re-match.

**`offer` is separate from `raw_offer`.** The listing is a thing that persists across
fetches; the raw rows are observations of it. Without that split, every fetch produces a
new offer and the match has to be made again from nothing each time.

**`brand_id` is repeated on `variant_mpn`.** A part number is only meaningful next to its
brand — two manufacturers reuse the same string freely — so the index has to be over the
pair, and that means the brand sits on the row.

### Region and currency

One domain, Europe, euro. `currency` stays a column rather than an assumption: the phrase
was "on this domain", other domains are therefore possible, and adding a currency to
`price_event` later is the migration this model has twice been shaped to avoid.

What one currency does not buy is one market. VAT is 19% in Germany and 23% in Portugal,
and both shops show the buyer a price with their own rate inside it. So the price is
stored exactly as the buyer sees it, and `seller.country` is stored next to it — not to
correct for the difference, but so that the difference can be explained rather than
looking like a better deal.

Whether a seller delivers to the buyer's country is a property of the seller, and until
it is modelled, "cheapest" on a card is cheapest for someone, not necessarily for the
person reading it.

### Open questions on this model

1. **How is a bundle recognised** from a title that does not use the word?
2. **Does a variant ever move category?** Its identity key is computed from that
   category's identity-bearing attributes, so moving it invalidates the key and every
   match the key produced.
3. **Does a seller deliver to the buyer?** Until that is modelled, the cheapest offer on
   a card is cheapest for somebody, not necessarily for the person reading it.

## Categories and visibility

A category is not only a classification. It is the lever an operator has over what the
storefront shows, so it carries two states that have nothing to do with each other.

### Two independent states

**Visible** is editorial. Hidden means the storefront does not show it. Fetching
continues, offers keep arriving, prices keep being recorded, nothing is deleted.
Unhiding brings the category back with its history intact rather than with a hole in it.

**Identity-ready** is technical: whether the category has its attribute definitions and
extraction rules. A category that is not ready still works — its variants simply have no
identity key and go the long way round, through the matcher and possibly the judge.

They are orthogonal on purpose. A category can be created and shown before the parser
understands it, which is exactly what lets one be added from the admin panel today and
wired into the parsers by hand afterwards. The categories that are visible but not yet
identity-ready are, between them, the engineering queue.

### Hiding cascades, and is computed once

Hiding a parent hides everything beneath it. So a variant is visible when its own
category is visible, and every ancestor of it, and its product.

Walking ancestors per query does not survive millions of variants. Effective visibility
is therefore denormalized onto the category and recomputed whenever the tree changes:
categories are few, the recompute is instant, and the storefront filter becomes a boolean
on an index instead of a recursion. This is not an optimisation to add later — a query
that recurses per row cannot be rescued afterwards.

### Visibility is a storefront concept only

The public API filters on it. **The admin API never does.** Whoever administers the
catalogue has to be able to open the exact thing they have just hidden, and a hidden
product that disappears from its own operator is a support question with no way to answer
it.

### Uncategorized is a real category, and it is hidden

An offer whose source category has not been mapped is not dropped and does not hold up
the pipeline. It lands in `uncategorized`, an ordinary category that happens to be
hidden. Nothing half-understood reaches the storefront, and nothing is lost on the way.

Unmapped source categories accumulate into a queue. Mapping one by hand moves the whole
batch of variants behind it into a real category, and hands them the identity-key fast
path at the same time.

### A seller is scoped to its source

Price history is keyed by seller, so the word has to mean something exact. A seller is
the party actually selling, identified within one source — not across sources.

An ordinary shop has exactly one seller, which is the shop itself, so nothing is
complicated by this. A marketplace has thousands behind one source, and treating that
source as the seller would draw a single price line through forty independent traders,
presenting the gaps between them as movement.

Deliberately not modelled: the same trader appearing on two marketplaces. That is a
second identity problem, it buys nothing for price comparison, and it can be added later
without touching what is stored.

### Managing a category is an audited action

Hiding a category, remapping one, editing the tree: each changes what the public sees,
and each happens through the admin panel. "Why did those products vanish last Tuesday" is
a question that gets asked, and the audit trail already in this codebase is where the
answer has to be — `set_target("category", id)` and the changes alongside it.

This also makes categories the first part of the parser to need CRUD endpoints on
`admin_router`. The rest of the pipeline is machinery and needs no interface of its own.

## Where the time goes

Only two steps can be slow. Everything else is microseconds and not worth optimising.

**Re-fetching.** The fix is to not do it: content hash, `ETag`, `Last-Modified`. An
unchanged page is not parsed, not normalized and not re-matched.

**Candidate generation.** The one step that can quietly become every offer against every
variant. It has to be an index lookup with a hard cap on what comes back:

- exact barcode → hash index;
- brand plus normalized part number → btree;
- otherwise trigram or vector similarity over the normalized title, capped.

If candidate generation returns a few dozen rows, the matcher and the judge are working
on a small enough set that nothing after them matters. If it ever scans, no amount of
tuning downstream will save it.

The judge is expensive per call rather than slow in aggregate, and is bounded by the two
mechanisms above: the pair cache and the feedback loop into the rules.

## Open questions

These need real data, not more thinking. Nothing below should be built until the first
one is answered.

1. **What share of pairs does the deterministic layer close?** Take 30–50 real offers
   from both kinds of source, including the same product sold by different shops, and
   measure it. Above roughly 90 per cent, the design above holds. Around 40, the centre
   of gravity moves to pulling identity out of free-text titles, and that becomes the
   first thing to build instead of the matcher.
2. **How often is a barcode actually present**, per source kind, and how often is it
   wrong when present?
3. **Which categories are in scope first?** Identity-bearing attributes have to be
   defined per category, and that work does not generalise.
4. **How fresh does a price have to be?** This sets the crawl budget, and the crawl
   budget sets everything about the fetch layer.

## Deliberately not decided yet

- Which queue or scheduler runs the crawl.
- Whether the search index is PostgreSQL or something separate. It is derived and
  rebuildable, so it can be swapped late.
- Which model judges pairs, and the prompt it is given.
- How a human reviews the unresolved queue.

All four are downstream of the answers above. Deciding them now would be guessing.
