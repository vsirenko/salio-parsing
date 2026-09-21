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
its own queue reason.

**The category is deliberately not a filter.** A brand arrives stated in a feed field; a
category is *inferred* by us, through a mapping or from text. Filtering on our own
inference can throw away the right answer and report it as absent.

**Five reasons, because "did not match" is five different kinds of work.**

| reason | what it means | who fixes it |
|---|---|---|
| `brand_unresolved` | the drawer could not be chosen | brand aliases |
| `no_signals` | nothing to match on at all | pulling identity out of titles |
| `signals_unmatched` | the catalogue has no such thing | create the variant |
| `ambiguous` | several plausible candidates | a human, or a pair judge |
| `low_confidence` | one candidate, too weak | not produced yet; needs a fuzzy rung |

A queue row carries the near misses that were considered, so deciding is a choice rather
than a search.

## Decisions worth knowing before changing it

- **An offer has an active match or a queue row, never both.** A second place answering
  "what is this listing" is a second place to disagree. A successful match deletes the
  queue row; unlinking writes one back.
- **Re-matching supersedes rather than overwrites.** The previous opinion and its evidence
  stay, held to one live row by a partial unique index. A link that turned out wrong is
  worth more as a record than as a deletion.
- **`evidence` says what the link is made of** — which signal fired and which values
  agreed. Without it a wrong match cannot be argued with, only deleted.
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
