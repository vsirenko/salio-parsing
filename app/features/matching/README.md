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
| `GET /api/admin/match-queue` | what could not be placed, with its listing and candidates — by `reason`, `shop_id`, `brand_id`, `category_id`, `search`, `include_snoozed`; `?sort=` |
| `GET /api/admin/match-queue/{offer_id}` | one queued listing |
| `POST · DELETE /api/admin/match-queue/{offer_id}/snooze` | set it aside until a time, or bring it back |
| `GET /api/admin/match-queue/summary` | the breakdown that says what to build next |
| `GET /api/admin/matching/judge/pending` | what each judge pass would pay for now, asking nothing |
| `POST /api/admin/matching/judge` | ask the judge about the brand choices, then retry them |
| `POST /api/admin/matching/judge/colours` | buy the colour a title carries and no rule may read |
| `POST /api/admin/matching/judge/matches` | ask whether each rule's match names the right model |
| `GET /api/admin/matching/doubts` | the matches the judge doubts, for a person to decide — by `method`, `shop_id`; `?sort=` |
| `POST /api/admin/matching/doubts/{offer_id}/keep` | a person looked and left the match where it is |
| `POST /api/admin/offers/{offer_id}/promote` | make the variant this listing was looking for |
| `POST /api/admin/matching/promote` | do that for everything identifiable in the queue |
| `POST /api/admin/matching/merge` | fold together the entries a barcode — or an Apple part number — says are one product |
| `GET /api/admin/matching/suspects` | what looks filed twice, with the evidence and the fix to make; changes nothing |
| `POST /api/admin/matching/merge/pair` | fold one chosen entry into another; refused where they differ on an axis unless `despite_axes` |
| `POST /api/admin/matching/rebuild` | rebuild the entries named after a reading that has since changed, and delete the empty families nothing points at |

## How it works

**Only a new listing is placed.** The catalogue's entries are new products, and a
refurbished or demo unit on one of them is that product's cheapest price: on 24.09.2026 ten
of mdata's refurbished tablets and eight of its demo `Galaxy S23 FE` stood on entries —
seventeen of those entries made from them — because its channel read the condition off the
name, which did not say it. `run` and `promote_queue` take only `offers.condition = new`,
so a listing marked otherwise is left alone rather than placed wrong. Where second-hand
stock should go instead is still open (TODO.md); a person can still place one by hand.

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

**Where the category says so, agreeing on the axes both sides carry is not enough.** A
category with `model_match_needs_full_identity` places by model only on a complete identity,
and a candidate nothing could check is no candidate at all; the listing goes on as unmatched
and, carrying a barcode, is promoted to an entry of its own. Laptops need it — a model is
dozens of configurations there — and phones and tablets do not, which is why it is the
category's setting and not the rung's (see `categories`). **An axis the listing's channel never publishes is
unknown, not missing:** 1a and bm state no keyboard on 96% of their laptops, and asked for it
none of their listings could be placed by model. An axis a channel carries on fewer than one
listing in ten, over fifty or more, is excused for that channel's listings; where the
candidates differ in exactly that axis the listing waits as `axis_unpublished`, and a match
that excused one learns no barcode, because it confirmed nothing about that axis.

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

**A colour a shop only wrote in its title is the other bought answer.** The category's
rule reads a colour out of a field and never out of a title, because across one shop's 1153
titled products the word takes 358 forms and canonicalising those by guessing splits one
product into several. 53 of the 57 listings stuck on a missing colour keep it in the title
and nowhere else, so there is nothing left to read and nothing left to count:
`POST /api/admin/matching/judge/colours` buys the answer, and the ladder and the promotion
bar consult the stored verdict exactly where they consult a bought brand — in `_identity`,
which is the one place a reading's axes and a bought axis meet.

**A bought colour is not taught to an entry somebody else made.** `_reconcile` writes what
the shop itself said and nothing else. A verdict is bought for one listing against one title
and one maker; written onto a shared entry it would reach every listing that entry ever
matches, which is more than was asked and more than was paid for.

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

**A rebuild moves an entry into the family its name says.** A catalogue entry made from
one listing is named after that listing's reading, and when the reading improves — a rule
fixed, a word entered in a registry — the entry keeps the old name. `POST /matching/rebuild`
renames it where no listing on it reads the name it has — two shops disagreeing about a
`5G` suffix keep the name they share, but a name neither of them reads is not shared, and
any reading beats a spec sheet — and then files it under the product the new name makes,
because the family is exactly what the model string says: that is the rule that made it. A rename used to stop at the entry, and 366 entries sat named `Galaxy S26` under a
family still headed `Galaxy S26 S942 5G Dual Sim`. **A family left empty is deleted, unless
something points at it.** It used to be hidden and kept, for the trail's sake, and on
25.09.2026 1506 of the 1508 hidden families held nothing while 15 audit entries named a
family at all: the list of families was mostly names of nothing. So a rebuild deletes a
hidden family with no entry in it, and keeps it hidden only where an audit entry names it
or a merge folded it — deleting that one would leave a record pointing at no row. A name
that is needed again makes a new family. The rebuild's own entries do not count: each
record it touched named itself the target on the way, so until it cleared that, its entry
named whichever family it touched last — 13 of the 15 entries naming a family on
25.09.2026, and none of them somebody acting on one. **An entry filed into a hidden family shows it
again**: nothing else hides a family, so a hidden one with an entry in it is only this
pass's leftover — on 23.09.2026 `Apple iPhone 16 Pro` and 60 tablet families sat off the
storefront that way, their names emptied by one reading and filled again by the next.

**What looks filed twice is a queue, not a hunt.** On 25.09.2026 every split was found by eye
— `Plus 16` beside `16 Plus`, a MacBook Air at 13.0 and 13.6, one part number on three
entries — and each was one of three shapes. `GET /matching/suspects` (`suspects.py`) finds
them and says what would fix each: one part number on entries of one maker that agree on
every axis they share (`merge`); two entries of one model that differ in one number, by
under 5% (`axis` — `1000 GB` against `1 TB` is 2.3%, two real capacities are further apart);
families whose names are the same words in another order or case (`registry`, naming the
spelling most entries carry); and a family named by a screen size (`reading` — `15.6`,
`15.6"` are the screen read as the model, which no alias can fix; a whole number is a name,
Dell's `16`, Nokia's `3210`). A part number with a
space in it is not a code — `Galaxy S25 256-Silverblue` is a piece of a title a shop put in
the field, 156 of the learned ones — and is not offered for a merge. It changes nothing, the
ones holding the most listings come first, and each carries its brand's and category's ids,
which the registry and a reparse are keyed by. A suspect a person agrees with is folded by
`POST /matching/merge/pair`, under the same axis guard as the passes.

**A part number merges where the maker's names one configuration.** Apple's does —
`MDH74ZE/A` is one MacBook Air with one keyboard — and 67 of 112 of its MacBook part numbers
sat on more than one entry. `ONE_PRODUCT_PART_NUMBERS` holds the makers measured to be like
that, Apple alone for now, and only the whole number with its region counts: on a Mac the
region letters are the keyboard. Samsung's `SM-S948B` covers a family, so elsewhere a part
number decides nothing, and either way a pair whose entries disagree on an axis is refused.

**An entry's axes follow its listings, as its name does.** Axes are set from the listing
that made an entry and only filled in by the ones that join it, so a reading that improves
leaves them behind: on 25.09.2026 MacBook Airs read 13.6" and 1 TB on every listing sat on
entries holding 13" and 1000 GB, and 101 pairs of entries one Apple part number named could
not be merged for it. A rebuild sets an identity axis to the value every listing on the
entry now reads (`realigned`), only when they all agree and only to a value the registry
knows; an entry that becomes one that exists is merged into it.

**A family takes the case its entries write.** The lookup that files an entry under a family
ignores case, so the spelling that made a family heads it for good: dateks's `PRO MAX 16
PLUS` stayed the storefront heading over 13 entries that all read `Pro Max 16 Plus` once the
registry spelled the name. A rebuild renames a family only when every entry in it agrees on
one spelling and that spelling differs from the family's name by case alone — anything more
is a different name, and that is a rename of the entries, not of the family.

## Working the queue

**A queue row carries what deciding needs.** `offer` is the listing as the shop wrote it —
title, shop, brand string, barcode, price, link, category — and `candidates` the near misses,
each named (`variant_title`, `model`, `brand`, how many listings `offers_count` already sit
on it) and compared with the listing axis by axis: `listing`, `entry`, and `agrees`, which is
null where one side is silent — the ladder treats a silence differently from a
disagreement, and so should whoever is choosing. The comparison is made when the row is
read, against the catalogue as it is, with the same values the ladder weighs — the reading's
identity and a colour the judge was asked for. **There is no score**: the ladder does not
rank candidates, it agrees or refuses, and a number here would be invented for the page. A
`brand_ambiguous` row's candidates are brands, not entries.

**`brand` and `model_key` are what the matcher looked for**, written onto the row as it
queues it: the brand it settled on, and the stated model normalized as the model rung
compares it (never the title — a whole title normalized groups nothing). `siblings` counts
the queued listings looking for the same pair, itself included, so `sort=-siblings` puts
first the one new entry that would place the most listings. That holds where a model names
a product; where it names a family it counts the family — nineteen of bigbox's `Dell Pro 14
Essential` configurations share one on 24.09.2026, and they are nineteen entries, not one.
A row queued before the columns existed has neither until the matcher next retries it, which
every pass does.

**A pass takes the least recently tried first**, the never tried before anything. In id
order every pass took the same first `limit`: with 1422 unplaced listings and a limit of
1000, the last 422 were never retried, whatever the catalogue had learned since.

**Snoozing hides a row until a time**, and the promotion sweep leaves it alone — a person
said not now, and making an entry of it is exactly what they deferred. The matcher still
retries it: the catalogue may grow the entry it needed. `include_snoozed=true` shows them.

**Keeping a doubt is a person's decision, not a flag.** `POST /doubts/{offer_id}/keep`
supersedes the rule's match with the same entry by the same `method`, now `decided_by:
human`, with `kept_rule_match` in its evidence. It leaves `GET /doubts`, which is only about
what a rule decided, and it survives the next pass as every human decision does. Placing it
by hand with `PUT /match` would do the second and lose the first: the method would read
`human`, and "which matches rest on a barcode" would no longer find it.

**`GET /doubts` reads the listing's title off `offers`, and joins the verdicts by
equality.** It used to pick the title out of every observation with a window over all the
readings — 7.5 s a page on 201 thousand of them — and the two agreed on all 18486 listings
when it changed; and it found each match's verdict with a subquery that compared JSON fields
of every verdict for every one of 17 thousand matches, which is 25 s. `POST /judge/matches` reads the same
column, so the question asked and the doubt looked up cannot name different titles.

## What cannot be undone, previewed

`promote` (one or the sweep) and `merge` take `dry_run=true`. The preview is the real code
inside a savepoint that is then rolled back, so it cannot drift from what a real run does:
`created` lists the entries a promotion makes (their `id` null on a dry run). A preview
leaves the trail with its envelope and no changes — the trail says what was done, not what
would have been.

**A merge lists every pair it tried, refused ones too.** Each carries the `gtin` that joined
them, `from` (folded in, disappears) and `into` (survives) with title, model, brand and how
many listings sit on each, and `outcome` with the refusal's `reason` and `detail`. The
refused pairs are the ones to read: one barcode on two makers or two categories is more
often a shop's data error than one product. **A barcode does not fold entries that disagree on an identity axis** —
`axes_differ`, with the axes in `detail`. On 24.09.2026 the preview would have folded, of
198 pairs, 66 whose titles named two colours and 34 two capacities: a listing carrying one
entry's barcode had been placed on the other, and the fix is moving that listing, not
making one entry of two products. An axis only one side holds is a gap and does not refuse.
A person merging by hand is not held to this. The entries are taken as they stood before the
pair was tried; an entry an earlier pair of the same pass already folded away shows its id
and nothing else, beside `not_found`.

**How long a pass takes**, measured from the trail's own durations on 24.09.2026, so a
caller can choose a `limit` that answers inside a request (about 30 s):

| pass | per item, worst seen | a safe `limit` |
|---|---|---|
| `POST /api/admin/matching/run` | 3.5 s the longest pass seen, whatever its `limit` | 1000 |
| `POST /api/admin/matching/promote` | 17 ms | 1000 |
| `POST /api/admin/matching/merge` | 90 ms | 300 |
| `POST /api/admin/matching/rebuild` | 75 ms | 300 |
| `POST /api/admin/matching/judge/ambiguous` | 195 ms (four questions at a time) | 150 |
| `POST /api/admin/matching/judge/colours` | 85 ms | 200 |
| `POST /api/admin/matching/judge/matches` | nothing for an answer already bought; a new one as the two above | 150 new |

These are synchronous on purpose for now; a pass the size of the queue belongs in a
background job with a run id and progress, as the collectors have — see `TODO.md`.

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
  The bar is every axis the **category** calls identity-bearing, known on both sides, not
  every axis the listing happened to carry. The difference is what silence means. Two of the
  three collected shops state no colour at all, so a red and a black listing from either of
  them carry the same axes, agree on all of them, and under the weaker reading that counted
  as full agreement — which is how a black phone's barcode reached a blue one's entry.
  `category_attributes.identity_bearing` is where a category says which attributes tell its
  products apart, and it is a property of the pair rather than of the attribute: a capacity
  separates two phones and would mean nothing on a monitor. A category that declares none
  leaves the older bar standing, because requiring nothing would make every match complete.
  Measured over the same three shops: learned barcodes 478 → 35, entries holding two colours
  157 → 50. The matches themselves are unchanged — what changed is which of them are trusted
  enough to write proof.
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
