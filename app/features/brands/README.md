# brands

What is written on the box, and every string a source might write instead.

## Endpoints

| | |
|---|---|
| `GET · POST /api/admin/brands` | list — with counts, `has_*` filters and `?sort=` — and create |
| `GET /api/admin/brands/resolve` | what a string resolves to — `q`, `titles_only` |
| `GET · PATCH /api/admin/brands/{brand_id}` | read or edit |
| `GET · POST /api/admin/brands/{brand_id}/aliases` | list and add aliases |
| `DELETE /api/admin/brands/{brand_id}/aliases/{alias_id}` | remove one |
| `GET · POST /api/admin/brands/{brand_id}/models` | list and add model names |
| `DELETE /api/admin/brands/{brand_id}/models/{alias_id}` | remove one |
| `GET /api/admin/brands/{brand_id}/rereads` | the re-reads its registry changes asked for, newest first |
| `POST /api/admin/brands/{brand_id}/reread` | ask for one by hand, for a `category_id` |

No delete on a brand: one variants point at cannot go, and one nothing points at costs
nothing to keep. **A rename retitles what the maker makes**: a family's and an entry's
title carries the maker's name and is composed when something it is built from changes, so
renaming `CAT` to `Cat` left every entry reading `CAT S75` until something else touched it.
`PATCH` with a new `canonical_name` composes them again through the catalogue
(`CatalogService.retitle_brand`), and the audit entry says how many. A wrong brand is merged, which is catalogue work and does not exist yet.

## How it works

**A brand row says how much it holds and how far it is set up**: `products_count`,
`variants_count`, `offers_count` (new listings on sale placed on its entries — the
catalogue's rule), `aliases_count` and `models_count`. Without them the list is an alphabet
of thousands with the busy beside the empty. `?sort=` takes any of them and `name`;
`has_products=false` finds brands left over from a merge, `has_aliases=false` brands no
shop's string can reach. The counts are correlated subqueries (`_brand_rows`), so a page
costs its own rows; `BrandRead` without them stays what `/resolve` nests.

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
name the catalogue uses, per brand **and per category**. A maker's names for its phones are
not its names for its tablets: keyed by brand alone, Nubia's phone `Air` was found whole in
`Apple iPad Air`, and 130 of m79's tablets would have read as it. A listing reads its own
category's page only, and the same spelling may be a model in two categories. `galaxy s26`, `s26` and `galaxy s26 5g` are three rows
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

**A brand can be a line of another** (`parent_id`): POCO of Xiaomi, Hammer of myPhone, RugOne
of Ulefone, nubia of ZTE, Honor of Huawei, Nokia of HMD. Shops write the parent in the brand
field and the line in the title — 70 POCO listings said `Xiaomi` and `Xiaomi Poco F9 Ultra` on
26.09.2026 — so the matcher takes the line a title names wherever the maker resolved to its
parent, and a rebuild moves the parent's entries whose listings all name one line. One level:
a line's parent is not itself a line (`parent_is_a_line`), and a brand is not its own
(`parent_is_self`). `null` takes it away.

**Registry work moves no ruleset version, so it asks for a re-read itself.** A hundred rows
entered here change no code, so nothing looks stale and nothing is recomputed — on
26.09.2026 renaming a thousand Apple listings took a laptop re-reading twenty thousand over
HTTP, three admin tokens and forty minutes. Adding or removing a model name leaves a
`reread_requests` row for the brand and the category, one open per pair and moved to now by
every change, and the scheduler takes it once the changes have been quiet for
`REREAD_QUIET_SECONDS`: 235 names entered in a row are one re-read. It reads only the
listings placed or queued under that maker there, a batch per tick, then settles — rebuild,
split, rebuild — and writes what that did on the request. A change arriving while one is
read starts it over, because the pages already read used the words as they were. See
[runs](../runs/README.md), "the scheduler".

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
