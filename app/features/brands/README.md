# brands

What is written on the box, and every string a source might write instead.

## Endpoints

| | |
|---|---|
| `GET · POST /api/admin/brands` | list and create |
| `GET /api/admin/brands/resolve` | what a string resolves to — `q`, `titles_only` |
| `GET · PATCH /api/admin/brands/{brand_id}` | read or edit |
| `GET · POST /api/admin/brands/{brand_id}/aliases` | list and add aliases |
| `DELETE /api/admin/brands/{brand_id}/aliases/{alias_id}` | remove one |
| `GET · POST /api/admin/brands/{brand_id}/models` | list and add model names |
| `DELETE /api/admin/brands/{brand_id}/models/{alias_id}` | remove one |

No delete on a brand: one variants point at cannot go, and one nothing points at costs
nothing to keep. A wrong brand is merged, which is catalogue work and does not exist yet.

## How it works

**A brand is what is on the box, not who owns the factory.** Procter & Gamble is not a
brand, Ariel is. The string that appears in a title and in a feed's brand field is the one
the matcher has to recognise, so that is what is stored. There is no manufacturer entity:
it would never take part in deciding whether two offers are the same thing.

**`normalization.py` decides what is computed and what is stored.** Case, whitespace, `®`
and one trailing legal form — `Co., Ltd.`, `GmbH`, and in the Baltics `SIA`, `UAB`, `OÜ` —
are computed away, so `SAMSUNG®` and `Samsung` are one row rather than two. Unicode is
NFKC-normalised first, because a feed can send a composed character that looks identical
and compares unequal.

A declension is not derivable and stays a row: `Samsungo → Samsung` is a fact somebody
established, because Lithuanian declines foreign names as grammar rather than as a
spelling mistake.

Only one legal form is stripped, and only at the end. `AS` is a legal form in Estonia and
a fine start to a brand name, so stripping it anywhere would eat real names.

**`kind` says where an alias may be read from**, not how confident we are — that is
`origin`. `Самсунг` and `Samsungo` *are* Samsung and are safe anywhere. `iPhone` is a line
Apple makes: a feed's brand field saying `iPhone` does mean Apple, but reading it out of a
title files "Spigen case for iPhone 15" under Apple. Every catalogue holds more accessories
than devices, so that is the main flow of errors rather than an edge case. `resolve` with
`titles_only=true` drops the `line` aliases for exactly that reason.

## The model registry

`model_aliases` is what a maker calls what it makes: every spelling a shop writes, to the
name the catalogue uses, per brand. `galaxy s26`, `s26` and `galaxy s26 5g` are three rows
and one model. The reader finds the longest of them whole in a title and takes the name —
see [offers](../offers/README.md), "the model is the registry's spelling".

It exists because two shops publish no model field, and cutting the model out of a title
by subtraction leaves whatever the shop wrote between the name and the capacity: 211 of
1524 catalogue entries were named `Galaxy S26 S942 5G Dual Sim` and the like. Subtraction
cannot be made clean, because the list of what to cut is open. Recognition can.

**It is vocabulary, and it is per brand.** Which words are a model is the same kind of fact
as which words are a colour, and lives in a table for the same reason. A name means
something only beside its maker — `Note 17` is Xiaomi's today and could be somebody
else's tomorrow — so an alias is unique per brand, not globally, the way a brand alias is.

**The canonical spelling is a string, not a row.** Several aliases point at one `model`,
and that is text rather than a foreign key to a product, the way `category_aliases` does
it: the registry is consulted by the reader and never joined to the catalogue, and a
canonical that was a key would tie a reading to a product row that may not exist yet.

**`normalize_model_name` keeps `+` and nothing else.** Words, casefolded, one space apart,
every other mark a separator. `+` stays because `Galaxy S26+` is not `Galaxy S26`, and it
is the one mark that says so. This is deliberately not `catalog.identity.normalize_model`,
which strips every separator to compare two designations; that one keeps the plus as well,
spelled out, so `S25+` and `S25 Plus` compare equal there while staying two spellings here.

**A name is at most six words**, and `ModelAliasCreate` refuses longer. The bound is what
makes finding a name cheap — every window of up to six words is looked up, however large
the registry — and it is a statement: anything longer is a spec sheet.

**Seeded from the shops that read cleanly, never from the catalogue.** `tools/seed_models.py`
reads every spelling off the eight sources whose model rules leave nothing behind and
writes each as an alias of itself, `origin='rule'`. Not from `products`: the junk is in
there too, and `Galaxy S26 S942 5G Dual Sim` sits whole in the title, so as the longest
known name it would win. Nothing is collapsed by the seed — `Galaxy S26 Ultra 5G` and
`Galaxy S26 Ultra` stay two names — because the same suffix is a real difference one line
over: Samsung sells a `Galaxy A16` and a `Galaxy A16 5G` as different phones. Making one an
alias of the other is a decision, entered by hand.

**Registry work moves no ruleset version.** A hundred rows entered here change no code,
so nothing looks stale and nothing is recomputed. Follow it with a reparse.

## Decisions worth knowing before changing it

- **The brand name is not unique.** Delta is taps, an airline and machine tools — separate
  companies that share a string, so they are separate rows and the slug is what separates
  them. Collapsing them to avoid the appearance of a duplicate would be the actual bug.
- **An alias is unique per brand, not globally.** `resolve` returning two brands is not a
  failure: one result is a deterministic signal, two are evidence the category has to
  settle from the brands that already have variants there, and none means the string
  belongs in the candidate queue.
- **Scoping a brand to a category** was the tempting alternative and is worse: Samsung
  sells in a dozen categories and would need a row in each, with its aliases repeated.
- **No confidence column.** Nothing would read it. Trust is `origin`; not-sure-yet is a row
  in `brand_candidate`, which is filled by ingestion and does not exist yet.
- The legal-suffix list is deliberately short and grows from what real feeds send. A long
  list eats real names.

See also `docs/parser-design.md`, "A brand alias is not one kind of thing".
