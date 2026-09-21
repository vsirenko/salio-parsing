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

In a mixed catalogue the variant axes are data, not schema. Each attribute a category uses
carries a flag: does changing it make this a different thing to buy? The flag sits on the
pairing rather than on the attribute, because the answer differs by category — see
[One canon](#one-canon-and-everything-normalized-onto-it).

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

**Markets and shops** is where trade happens: the storefronts we run, the shops whose
offers appear in them, the channels we read those offers through, and the sellers behind
them.

**Offers and prices** is what flows through the pipeline: listings, the raw bytes behind
them, the matches linking them to variants, and the price history that falls out.

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

### One canon, and everything normalized onto it

Sources name the same thing differently — `Цвет`, `Color`, `Krāsa`, `Spalva` — and half
the time do not send it as a field at all, leaving `256GB` to be pulled out of the title.
So there is one canonical registry of attributes, and everything is normalized onto it.

That is what makes the two extraction paths interchangeable. Once a param and a phrase cut
out of a title both resolve to `capacity = 256 GB`, where the value came from stops
mattering to everything downstream.

**The attribute is global, its use is per category.** `value_type`, the unit dimension and
the rounding scale belong to the attribute itself: capacity is measured in gigabytes
wherever it appears. Whether it *carries identity* belongs to the pair, because that genuinely
differs: weight is an axis for food — 500 g and 1 kg are different products — and a
specification for a washing machine.

**One attribute, or two?** Only if the values mean the same thing everywhere. Size 42 in
shoes and size 42 in clothing are different scales, so they are `shoe_size` and
`clothing_size`, and nothing is lost by saying so.

**Inheritance down the category tree is deliberately absent.** With a hand-managed tree it
is a handful of rows per category, created by a button. More to the point, inheritance is
a read rule rather than a storage one: if the tree grows enough to want it, it can be
added without touching a stored row.

### Filling it: lookup, parse, and a queue that drains

Two different mechanisms, and the difference decides how much manual work there is:

- a **key** (`Atmiņa`) and an **enum value** (`Melns`) are *looked up* in the alias tables;
  no match means a row in a candidate queue;
- a **number** (`256 GB`) is *parsed* — value, unit, conversion to the base unit, rounded
  to the attribute's scale. It either parses or it does not, and it never queues.

So capacity, weight, screen size and power — most of what a spec sheet holds — generate no
queue at all. Only enumerations do: colour, material, connector type.

**The queue is the data-entry tool, not an error log.** The registry starts empty and
nothing resolves, which is the normal beginning. Someone opens the queue for a category
once and sees what the data actually says, ordered by how often it says it:

```
Krāsa      8 142   -> create `color`
Цвет       6 907   -> alias of color
Color      3 220   -> alias of color
Atmiņa     7 880   -> create `capacity`
Garantija  5 120   -> skip, a warranty is not an axis
```

Nobody invents a specification sheet up front; they pick out of what arrived. `identity_ready`
on a category therefore means "we chose the two or three that separate variants", not "we
described every characteristic" — an order of magnitude less work.

**The judge proposes, the alias table remembers.** `Atmiņa → capacity` and `melns → black`
are translation, which an LLM does reliably, so the judge pre-fills the queue and a human
confirms in batches. After that the next eight thousand offers saying `Krāsa` never reach
it. Attributes are where that loop pays best: the language variants are many but finite.

**And the queue drains.** Distinct keys in a category are a handful; distinct colour names
across every source are a few hundred and dry up quickly. New products never stop arriving;
new attribute names do, within weeks of opening a category.

**Nothing unmapped is lost.** An unresolved key stays in `normalized_offer.attributes` as it
arrived. It simply takes no part in identity, so the price of not having mapped it yet is
the slow path rather than missing data, and the pipeline never blocks on a word nobody has
classified.

### A variant's attributes are a consensus, not a copy

They live in `variant_attribute`, one row per attribute, with the value in a typed column:
a number in its base unit, or a foreign key to a canonical enum value. Typed columns rather
than one text field, because faceting and range filtering are the storefront — "6 to 7
inches", "256 GB (1 240)" — and casting a text column per query is not a way to serve that.

There is no `identity_attrs` blob beside it. Specifications need a home regardless, and
keeping the identity-bearing ones somewhere else would be two mechanisms for one thing.
`identity_key` stays on the variant, computed once at write time from the rows whose
`category_attribute.identity_bearing` is set.

**Ten offers for one variant do not agree.** One says the colour is black, another
graphite, a third says nothing. So the variant holds a *reconciled* value, by weighted
majority: a feed outweighs a scrape, and a param outweighs something cut out of a title —
which is what `source_kind` is for. The rule improves on its own as offers accumulate.

A value set by a human carries `origin = human` and is never overwritten by that
reconciliation. Otherwise a correction survives exactly until the next crawl.

**Flipping `identity_bearing` invalidates every key in that category.** The key is computed
from the identity-bearing set, so changing the set means recomputing and re-matching all of
it. That is not forbidden, but it is an operation the size of a migration rather than a
checkbox, and the admin panel should say so — or somebody will one day untick it out of
curiosity.

### A brand alias is not one kind of thing

A brand is what is written on the box, not who owns the factory. Procter & Gamble is not
a brand, Ariel is; the string that ends up in a title and in a feed's brand field is the
one the matcher has to recognise, so that is what is modelled. A manufacturer entity
would never take part in deciding whether two offers are the same thing.

**Two kinds of alias, because they may be read from different places.**

`Самсунг`, `Samsungo`, `Samsung Electronics Co., Ltd.` are the same brand spelled
differently. `iPhone` is not Apple — it is a line Apple makes. The difference is not
philosophical, it breaks things:

```
title:  "Spigen case for iPhone 15 Pro"
brand:  Spigen
```

With `iphone` sitting among Apple's aliases like any other, reading the brand out of the
title yields Apple, and a Spigen case is filed under the wrong maker. Any catalogue holds
more accessories than devices, so that is the main flow of errors rather than an edge
case — while a feed's brand field saying `iPhone` does mean Apple, reliably.

So `kind` answers "where may this be read from", not "how sure are we":

- `spelling` — another way of writing the same brand. Safe anywhere: the brand field and
  the title alike.
- `line` — a product line. The brand field only, never inferred from a title.

**Normalization is a function; declension is a row.** Case, punctuation, `®` and legal
suffixes — `Co., Ltd.`, `GmbH`, and in the Baltics `SIA`, `UAB`, `OÜ` — are computed away,
so `SAMSUNG®` and `Samsung` are one row rather than two. Uniqueness is on the normalized
form. What no rule derives is a row: `Samsungo → Samsung` is a fact somebody established,
not something a function can work out, and Lithuanian declines foreign names as a matter
of grammar.

**Two brands can own the same string, and that is not a duplicate.** Delta is taps, an
airline and machine tools; Nova, Atlas, Titan and Elite are ordinary words a dozen makers
have registered. Those are separate companies that happen to share a name, so they are
separate rows — the brand's *name* is not unique, its *slug* is, and `delta` and
`delta-tools` is what every catalogue ends up doing anyway. Collapsing them into one row
to avoid the appearance of a duplicate would be the actual bug.

Tying the brand itself to a category is the tempting fix and the worse one. Samsung sells
phones, televisions, washing machines, monitors and drives; scoping brands to categories
would give it a row per category and every alias would have to be repeated against each.
It fixes Delta by breaking Samsung.

**The ambiguity is resolved from data, not from a mapping.** When `delta` leads to two
brands, the question to ask is which of them already has variants in the category this
offer landed in — and `variant.brand_id` and `variant.category_id` already answer it. No
column, nobody to maintain it, and it corrects itself as the catalogue grows.

An earlier draft of this put a category on the alias instead. It would have had to be
filled in by hand, and it would only ever have been filled in after somebody was bitten.

Cold start is the one case the data cannot settle: two Deltas, neither with a variant yet.
That is not a guess to make, it is a `brand_candidate` for a human to resolve once — which
is the mechanism that already exists rather than another column.

**Unknown brand strings queue rather than become brands.** A feed sending a string we do
not know must not create a brand, or one seller's typo is canon forever.
`brand_candidate` holds it with a count of how often it has been seen, and the count is
what sorts the queue by usefulness: `Samsng` from a single offer does not compete with a
real brand seen a thousand times. This is the same shape as unmapped source categories,
and for the same reason.

**No confidence column.** What would `0.7` on an alias mean — who compares it to a
threshold, and what happens either side? `offer_match` keeps one because something reads
it — the decision policy refuses to link below a threshold — and that is exactly the test
a number has to pass. Trust here is already carried by `origin`: a rule, the judge, a
human. The "not sure yet" case is not a low number on an alias, it is a row still
sitting in `brand_candidate`. Keeping the line between known and suspected at the boundary
between two tables makes it one that cannot be quietly blurred.

**Deliberately not an entity: the product line.** `iPhone`, `Galaxy` and `MacBook` could
be a table of their own, which would give the storefront a grouping and help pull a model
out of a title. For matching, `kind = line` does the same work far more cheaply, and the
storefront that would want the grouping does not exist. If it ever does, the type becomes
a table without losing anything stored.

### The full shape

Four groups. The taxonomy and the catalogue are what identity is decided against; markets
and shops are where trade happens; offers and prices are what flows through the pipeline
into them. `[built]` marks what exists in the database today — where it does, the table is
named in the plural (`countries`, `currencies`, `markets`) while this document names the
entity in the singular throughout.

```
-- Where and in what money ----------------------------------------------------

currency       code char(3) PK, name, symbol, minor_units              [built]
country        code char(2) PK, name, currency_code -> currency,       [built]
               vat_standard_rate NULL, is_eu
market         code char(2) PK -> country.code, name,                  [built]
               slug UNIQUE, languages[], is_enabled
               CHECK cardinality(languages) > 0

-- Who is selling ------------------------------------------------------------

shop_group     id, slug UNIQUE, name           -- one brand across countries; optional
shop           id, shop_group_id NULL, country_code -> country,
               slug UNIQUE, name, website, is_marketplace, rating NULL
shop_market    shop_id, market_code, is_enabled     -- where its offers are shown
               PK (shop_id, market_code)
source         id, shop_id, kind(feed|api|scrape), trust, base_url, is_enabled
seller         id, shop_id, external_id, name
               UNIQUE (shop_id, external_id)

-- Taxonomy -------------------------------------------------------------------

category       id, parent_id NULL, slug UNIQUE, name,
               is_visible, is_visible_effective, identity_ready
category_market_stats  category_id, market_code, offer_count, refreshed_at
attribute      id, key UNIQUE, name, value_type(enum|number|bool|text),
               unit_dimension NULL, scale NULL
                             -- one canonical registry: color, capacity, screen_size
attribute_alias        id, attribute_id, alias_normalized, language NULL, origin
                             -- Цвет, Krāsa, Colour -> color
category_attribute     category_id, attribute_id, identity_bearing, position
               PK (category_id, attribute_id)
                             -- which attributes a category has, and which carry identity
attribute_value        id, attribute_id, canonical, position
attribute_value_alias  attribute_value_id, alias_normalized, language NULL, origin
attribute_candidate    id, alias_normalized, alias_raw, category_id NULL,
               seen_count, first_seen_at, resolved_attribute_id NULL, resolved_by
               UNIQUE (alias_normalized, category_id)
attribute_value_candidate  id, attribute_id, alias_normalized, alias_raw,
               seen_count, first_seen_at, resolved_value_id NULL, resolved_by
               UNIQUE (attribute_id, alias_normalized)
source_category_map    source_id, source_path, category_id, mapped_by, mapped_at
               UNIQUE (source_id, source_path)

-- Catalogue ------------------------------------------------------------------

brand          id, slug UNIQUE, canonical_name      -- the name is NOT unique
brand_alias    id, brand_id,
               alias_normalized,         -- case, punctuation and legal suffix removed
               alias_raw,                -- as seen, for display and provenance
               kind(spelling|line),      -- where this alias may be read from
               origin(rule|judge|human)
               UNIQUE (alias_normalized, brand_id)
               INDEX (alias_normalized)
brand_candidate        id, alias_normalized, alias_raw, source_id NULL,
               seen_count, first_seen_at, last_seen_at,
               resolved_brand_id NULL, resolved_by, resolved_at
               UNIQUE (alias_normalized)
product        id, slug UNIQUE, brand_id, category_id, title, is_visible
product_merge  from_id, into_id, merged_at, reason, decided_by
variant        id, slug UNIQUE, product_id NULL, brand_id, category_id, title,
               kind(single|multipack|bundle), unit_count,
               identity_key NULL UNIQUE
               CHECK (kind = 'multipack') = (unit_count > 1)
variant_attribute      variant_id, attribute_id,
               value_num NULL,          -- base unit, rounded to the attribute's scale
               value_id NULL,           -- -> attribute_value, for enums
               value_bool NULL,
               value_text NULL,         -- never identity-bearing
               source_kind(param|title), origin(consensus|human)
               PK (variant_id, attribute_id)
               CHECK exactly one value_* is set
               INDEX (attribute_id, value_id)     -- facet by enum
               INDEX (attribute_id, value_num)    -- facet and range by number
variant_gtin   variant_id, gtin, origin, first_seen_at        -- INDEX (gtin)
variant_mpn    variant_id, brand_id, mpn_normalized, origin, first_seen_at
                                                              -- INDEX (brand_id, mpn)
variant_merge  from_id, into_id, merged_at, reason, decided_by
variant_component      bundle_id, component_variant_id, qty

-- Offers and prices ----------------------------------------------------------

offer          id, seller_id, market_code, external_id, url,
               condition(new|refurbished|used), condition_grade NULL,
               price, currency_code, availability, first_seen_at, last_seen_at
               UNIQUE (seller_id, external_id)
raw_offer      id, offer_id, source_id, payload, content_hash,
               fetched_at, last_seen_at
               UNIQUE (offer_id, content_hash)
normalized_offer       id, raw_offer_id, ruleset_version,
               title, brand_id NULL, category_id NULL,
               gtin NULL, mpn NULL, model NULL,
               attributes JSONB, price, currency_code, condition
offer_match    id, offer_id, variant_id, method, confidence, evidence JSONB,
               decided_at, decided_by, superseded_at NULL
               UNIQUE (offer_id) WHERE superseded_at IS NULL
price_event    id, variant_id, seller_id, market_code, condition,
               price, currency_code, at
               PARTITION BY RANGE (at)
               INDEX (variant_id, condition, at DESC)
judge_verdict  pair_fingerprint UNIQUE, verdict, reason, model, decided_at
```

Four things in there are decisions rather than plumbing:

**There is no `variant_id` on `offer`.** The active match is the row in `offer_match`
whose `superseded_at` is null, held to one by a partial unique index. A column would be
faster to read and would quietly destroy the previous answer on every re-match.

**`offer` is separate from `raw_offer`.** The listing persists across fetches; the raw
rows are observations of it. Without that split, every fetch produces a new offer and the
match has to be made again from nothing each time.

**`source` and `seller` both hang off `shop`, separately.** A shop with a feed and a
scraper is one shop, one seller and one offer, with `raw_offer.source_id` remembering
which channel saw it. Hang the seller off the source instead and the same shop becomes
two sellers, the same listing two offers, two lines in the price history and two shops on
the card.

**`brand_id` is repeated on `variant_mpn`.** A part number is only meaningful next to its
brand — two manufacturers reuse the same string freely — so the index has to be over the
pair, and that means the brand sits on the row.

### Slugs are entered where a human creates the row

A slug is a public URL, so it must not move on its own. Deriving it from a name means a
rename silently breaks every link to the thing. So `shop`, `category`, `brand` and
`market` have their slug entered, with generation offered as a suggestion in the form and
nothing more. The database checks the shape, because a malformed slug is a 404 that looks
like an application bug.

That rule cannot hold where the machine creates the row. Products and variants arrive
from offers in their millions, so their slug is derived from the title with the id
appended — `iphone-15-pro-128gb-14237`. Collisions become impossible by construction, and
a retitle does not break the link because the tail survives.

The slug never replaces the key. A natural key is right where the code comes from outside
and does not change (`EUR`, `LV`); where the identifier is ours and editable, the row
keeps a stable key and the slug is a unique column beside it.

`market.slug` is the exception worth naming: changing it moves every URL of a storefront
rather than one page, so until there is a redirect table, a live market's slug is fixed.

### Markets, shops and where money is charged

The storefronts are Latvia first, then Lithuania and Estonia, all in euro. Adding one has
to be data rather than a release, which is what shapes the three entities below.

**A market is a country we have decided to sell in.** `country` holds every country we
need to be able to describe — a German shop delivering to Riga needs a row there — and
`market` holds the storefronts. The country code is the market's primary key and its
foreign key at once, so two markets in one country are impossible by construction rather
than by convention. It is also what `offer` and `price_event` carry, where two characters
instead of an eight-byte id is worth a couple of gigabytes.

**A market is created disabled.** It is wired into the parsers, its categories are mapped,
and only then is it shown. That is what makes adding Lithuania a process rather than a
release, and nothing about it is seeded: countries and currencies are facts about the
world and belong in a migration, opening a market is a decision.

**A language is not a market.** Latvia read in Russian is the same prices, the same shops
and the same delivery, so languages are an ordered list on the market and the first one is
the default. Splitting them into two markets would double the catalogue for a UI toggle.

**A shop is not a source.** The shop is the commercial party a buyer deals with; the
source is the channel we get bytes through, and its trust — a feed carrying barcodes is
not a title scraped out of markup — has nothing to do with the shop's rating among
buyers. One shop may have several sources.

**A seller is scoped to its shop.** An ordinary shop has exactly one, which is the shop
itself. A marketplace has thousands, and treating the marketplace as the seller would draw
one price line through forty independent traders and present the gaps between them as
movement. Deliberately not modelled: the same trader on two marketplaces. That is a second
identity problem which buys nothing for price comparison.

**One currency does not mean one market.** VAT differs across Latvia, Lithuania and
Estonia, and it changes — Estonia raised its rate recently. Each shop shows a buyer a
price with a rate already inside it, so the price is stored exactly as the buyer sees it
and the rate is kept on the country only to explain a difference, never to recompute one.
The rate is nullable and unknown by default, because a wrong rate explains a difference
wrongly and silently.

`currency` stays a column on `price_event` rather than being derived from the market. The
market's currency is a mutable lookup; a recorded price has to say what it was in, or
editing one row of a reference table retroactively rewrites the meaning of the whole
history.

**Whether a shop delivers to the buyer** is `shop_market`, and it carries its own
`is_enabled`: a shop may deliver to Lithuania while we choose not to show it there yet.
Until that table is populated, "cheapest" on a card is cheapest for somebody, not
necessarily for the person reading it.

### Open questions on this model

1. **How is a bundle recognised** from a title that does not use the word?
2. **Does a variant ever move category?** Its identity key is computed from that
   category's identity-bearing attributes, so moving it invalidates the key and every
   match the key produced.
3. **How is a shop's delivery reach discovered?** `shop_market` records it, but nothing
   fills it in: a feed rarely states which countries it ships to, and a scraped page
   states it in prose.
4. **What happens to a slug when a shop is renamed?** There is no redirect table, so a
   changed slug is a dead link. For a market it is worse — every page of that storefront
   moves at once.

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

### Empty is hidden without anyone deciding it

Visibility above is one flag for all markets, and that is deliberate. Launching Lithuania
with three shops leaves most categories with nothing in them there, and they should not
appear — but the reason is not editorial, it is that there is nothing to show. That is
computable, so it is computed.

A flag per category per market would be the obvious alternative and is worse: the
editorial work would multiply by the number of markets, to express something the data
already knows.

The cost is honest and worth naming. "Does this category have an offer in Lithuania" over
millions of offers is not a question to ask per page view, so `category_market_stats`
keeps the count and a job refreshes it. A storefront tolerates that being a few minutes
stale — a category does not need to appear the instant its first offer lands.

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
5. **How much does the Baltic language mix cost the matcher?** The same television is
   `Samsung televizors`, `Samsung televizorius` and `Samsung teler`, plus Russian and
   English on the same sites. Fuzzy title comparison barely works across that, which
   raises the weight of brand and part number — both language-neutral — and lowers the
   weight of anything reading a title. Worth measuring alongside the first question,
   because it decides where the effort goes.

## Deliberately not decided yet

- Which queue or scheduler runs the crawl.
- Whether the search index is PostgreSQL or something separate. It is derived and
  rebuildable, so it can be swapped late.
- Which model judges pairs, and the prompt it is given.
- How a human reviews the unresolved queue.

All four are downstream of the answers above. Deciding them now would be guessing.
