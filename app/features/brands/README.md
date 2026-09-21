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
