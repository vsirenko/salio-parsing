# matching

Placing a listing in the catalogue, or saying exactly why it could not be placed.

## Endpoints

| | |
|---|---|
| `POST /api/admin/offers/{offer_id}/match` | run the ladder on one listing |
| `PUT /api/admin/offers/{offer_id}/match` | a human places it |
| `DELETE /api/admin/offers/{offer_id}/match` | unlink, back to the queue |
| `GET /api/admin/offers/{offer_id}/matches` | every opinion ever held about it |
| `POST /api/admin/matching/run` | work through what is unplaced |
| `GET /api/admin/match-queue` | what could not be placed, filterable by `reason` |
| `GET /api/admin/match-queue/summary` | the breakdown that says what to build next |
| `POST /api/admin/matching/judge` | ask the judge about the brand choices, then retry them |
| `POST /api/admin/offers/{offer_id}/promote` | make the variant this listing was looking for |
| `POST /api/admin/matching/promote` | do that for everything identifiable in the queue |

## How it works

**A ladder of signals, strongest first.** Each rung is an index lookup rather than a scan;
one hit is a match, several are `ambiguous`, none moves down a rung.

| rung | signal | confidence | why it sits there |
|---|---|---|---|
| 1 | barcode | 1.00 | proof, and needs no brand resolved first |
| 2 | brand + part number | 0.95 | a part number only means something beside its maker |
| 3 | brand + normalized model | 0.80 | language-neutral, which is what survives across three languages |

`identity_key` is declared in the method list and not produced: it needs an offer's
attributes resolved to the canonical registry, and nothing does that yet.

**Every rung below the barcode is checked against the identity axes**, and they are checked
differently, because the two signals fail differently.

A model string names a family *on purpose*: `Galaxy S26 Ultra 5G` is the 256, the 512 and
the terabyte alike, and matching on it alone once filed fifteen listings spanning a thousand
euros as one entry. So a candidate has to be **confirmed** before it is believed, and one
with no axis in common is `low_confidence` rather than a match.

A part number is *meant* to name the thing you buy, and on one shop it does. On another it
does not: `CPH2865` is bigbox's Oppo Reno16 5G at 256 GB and at 512 GB, in two colours, and
five of its twenty matches on this rung had pulled two capacities onto one variant. So a
candidate that **contradicts** an axis is dropped, while one with nothing to compare is
still taken. Requiring confirmation here instead would stop the rung firing on every
category whose axes nobody has written yet.

That is the whole of the difference: below, nothing is believed until something confirms it;
here, everything is believed until something contradicts it.

**The brand is a hard filter, and has to be resolved first.** That is the blocking step —
it turns matching from a scan into a lookup in a small drawer. It is also where it goes
quietly wrong: a brand resolved to the wrong row means searching the wrong drawer and
correctly finding nothing, which looks exactly like a catalogue that is missing a row. So a
brand string that resolves to nothing, or to two brands, does not get guessed at — it gets
its own queue reason, and those two are separate reasons: one has to be researched, the
other only has to be chosen between.

**A string that means two brands is never settled by an alias.** `Delta` belongs to the tap
company and the tool company equally legitimately, so no row can be added that makes the
ambiguity go away — it is decided per listing. That is the one gap more data does not close,
and the only place an outside judgement earns its cost: `POST /api/admin/matching/judge`
asks [the judge](../judge/README.md) about exactly that bucket and retries what it answers.
The ladder itself never calls out; it reads stored verdicts and nothing else, so running the
matcher stays offline, deterministic and as fast as its indexes.

**The category is deliberately not a filter.** A brand arrives stated in a feed field; a
category is *inferred* by us, through a mapping or from text. Filtering on our own
inference can throw away the right answer and report it as absent.

**Six reasons, because "did not match" is six different kinds of work.**

| reason | what it means | who fixes it | candidates on the row |
|---|---|---|---|
| `brand_unknown` | the string names no brand we have | read it, name the brand, add an alias | none — there is nothing to offer |
| `brand_ambiguous` | the string names several brands | pick one | the brands |
| `no_signals` | nothing to match on at all | pulling identity out of titles | none |
| `signals_unmatched` | the catalogue has no such thing | create the variant | none |
| `ambiguous` | several plausible variants | a human, or a pair judge | the variants |
| `low_confidence` | one candidate, too weak | not produced yet; needs a fuzzy rung | the variant |

A queue row carries the near misses that were considered, so deciding is a choice rather
than a search.

**A model string names a family, not a thing you can buy.** `Galaxy S26 Ultra 5G` is the
256, the 512 and the terabyte alike, and matching on it alone filed fifteen listings
spanning a thousand euros as one catalogue entry — 44 of 96 such entries merged capacities.
So the candidates that rung produces must agree on the identity axes before one is
accepted, and what the rung was reaching for — the family — is the **product** level:
a promoted variant joins the product for its brand, category and model, and several
capacities of one phone become several variants of one product. After the change, none of
either rung's entries merge a capacity.

The check applies only when the listing brought an axis to check with. Without one there is
nothing to disagree about, and refusing on that basis would stop the rung firing until
every category and every shop were furnished. When the listing has an axis and the candidate
has none, that is neither a match nor a miss: it is `low_confidence`, which until now had no
producer.

**The catalogue starts from listings, because only the shops know what is in them.**
Promotion makes a variant out of a listing and then lets the ordinary ladder place it, so
the link records the rung that actually fired rather than a method meaning "we made this
from itself"; where a variant came from is in the audit trail. A sweep takes only what
carries a barcode and comes from a channel we trust, because a variant made from a junk
listing cannot afterwards be told from a real one. It also refuses a shop's title in place
of a model: an entry named after a sentence cannot be searched for, groups with nothing, and
looks like a real product.

**A signal that was used outranks one that was not.** A barcode needs no brand — the first
rung runs before the brand is looked at — so a listing whose barcode was tried and missed is
`signals_unmatched`, whatever its brand turned out to be. Part numbers and model strings are
the other way round: both search inside a brand, so an unresolved one really is what stopped
them. The distinction was earned on real data, where 520 listings with a barcode on 99.6% of
them all came back `brand_unknown` and the truth was an empty catalogue — the difference
between being sent to write brand aliases and being sent to fill the catalogue. The last column is the difference that matters when picking what to automate
next: a bucket with candidates can be finished by choosing, and choosing is the only thing
a judge does. A bucket without them needs someone to go and look first.

## Decisions worth knowing before changing it

- **An offer has an active match or a queue row, never both.** A second place answering
  "what is this listing" is a second place to disagree. A successful match deletes the
  queue row; unlinking writes one back.
- **Re-matching supersedes rather than overwrites.** The previous opinion and its evidence
  stay, held to one live row by a partial unique index. A link that turned out wrong is
  worth more as a record than as a deletion.
- **`evidence` says what the link is made of** — which signal fired and which values
  agreed. Without it a wrong match cannot be argued with, only deleted.
- **`method` is the rung that fired; `decided_by` is what had the final say.** They come
  apart when a judge chose the brand and a rule then matched the model: the method is still
  `brand_model`, `decided_by` is `judge`, and the evidence carries the answer and its
  confidence. Keeping both is what makes "which matches rest on a model's opinion" a query
  rather than an archaeology exercise.
- **A match fills in axes the entry never had.** `variant_attributes` says of itself that
  it holds an attribute "reconciled across its offers", and until recently it was not: axes
  were written once, when a listing became an entry, and never again. An entry made from a
  shop that states no colour therefore had none for good — and the comparison only weighs
  the axes both sides carry, so colour could separate nothing. One `Nokia 3210` held the
  black, the blue and the gold; 327 entries held two colours at once. Filling the gaps from
  a match took that to 157.
  Gaps only, never an answer already there: a shop states 512 GB for a phone whose own title
  reads `4/128GB`, and letting whichever listing arrived second overwrite the first would
  make the catalogue depend on crawl order. And only from a match that proved something — a
  barcode always, a rung below it only where the axes it compared agreed.
- **A confirmed model match keeps the barcode it was made without.** The rung below the
  barcode is only reached because the barcode found nothing, and that barcode was then
  dropped — so the next pass redid the same work, forever. Of 207 barcodes the two collected
  shops share, 88 were on no variant for exactly this reason. Recording it moved 118
  listings onto the barcode rung and took the shared barcodes on a variant from 119 to all
  207. Only from a match an axis confirmed: a model match is a conclusion, not proof, and
  writing its barcode onto the variant turns the conclusion into proof — every later listing
  with that barcode would match at confidence 1.00, and a wrong one could not be argued with
  afterwards. `variant_gtins.origin` is `rule` for these, so what was learned can be told
  from what was collected.
  The bar is every axis the listing carried, not one of them. Agreeing on capacity while the
  entry has no colour to disagree with is not agreement, and treated as such it put a black
  phone's barcode onto a blue one's entry — permanently, at confidence 1.00 from then on.
  Tightening it took the learned barcodes from 758 to 478 with no loss of matching.
  What remains is not a comparison that is too weak but data that is not there: two shops
  state no colour at all, so their red and their black listings are indistinguishable to
  anything that reads them. The bar that would settle it is every axis the *category* calls
  identity-bearing, known on both sides — `category_attributes.identity_bearing` exists for
  exactly that and nothing consults it yet.
- **A match rewrites this listing's price and availability rows** to point at the variant.
  That is the cost of denormalizing the hint onto the series, and it is real: the number of
  rows rewritten grows with how long the listing has existed. Bounded to one listing, which
  is what makes it affordable — but a re-match is heavier than it looks.
- **A queued offer is retried, not duplicated.** The catalogue it failed against changes
  underneath it, so `attempts` counts and the reason is refreshed.
- **`GET /match-queue/summary` is the point of the whole feature.** It counts what happened
  when the signals were used, not how many offers carry a barcode — those are different
  numbers, and only the first one decides anything. Mostly `signals_unmatched` means the
  work is creating variants; `ambiguous` is the only bucket a pair judge helps with, and if
  it is nearly empty then a judge is not what this needs.

See also `docs/parser-design.md`.
