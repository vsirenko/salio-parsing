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
