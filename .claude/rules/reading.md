## Reading a payload

- Reading is layered general to specific, and what changes down the list is **what selects
  each layer**: nothing, the category, the shop, the channel, `(category, brand)`,
  `(category, brand, line)`, nothing. `app/features/offers/normalization/rules.py` holds the
  ordering and the reasons for it. Later wins.
- **A rule returns only what it changed.** A rule that found nothing returns `{}`, never a
  `None` that would erase what an earlier layer found.
- **A rule is an object with a `why`**, and the `why` is the case from the data that put it
  there — not a restatement of the code. "Normalises the model" explains nothing; "this
  shop's article numbers all begin `Y0000` and can never agree with another shop" can be
  argued with. Rules are objects so that the set an offer will get is readable *before* any
  of them runs; a chain of conditionals answers that only by being executed.
- **A rule may be declared with no body.** `Rule.pending` is a gap that is visible, which
  beats one that is not. Half a canonicalisation is worse than none: a colour mapped wrongly
  splits one product into several, confidently.
- **Rules are written against collected bytes, never against a guess.** Collect, measure,
  then write — and put the measurement in the `why`. A source with no ruleset is read
  generically, and the coverage on its run is what says which rules it needs.

## A version, and what it does not cover

- **`ruleset_version` is what decides whether a stored reading is stale.** A re-read
  compares it and keeps the row when it matches, so editing a rule and leaving the version
  alone is a fix that reaches nothing: the reparse sees the same string, every row stands,
  and the rule looks broken. That happened three times in one afternoon before it was
  guarded.
- **Bump the version when a *body* changes, not only when a rule is added.** A helper the
  body calls counts, and so does a constant or a regex it reads —
  `tests/test_normalization_layers.py` fingerprints the whole module and fails naming the
  ruleset whose version has to go up. Move the version and the fingerprint in the same
  commit; they are two values that have to agree, so forgetting one is loud.
- **A fingerprint covers what the module imports**, so a shop's rules for a second category
  go in a module of their own when they import that category: `sources/bigbox_laptops.py`
  beside `bigbox.py`. Kept in one file, every change to how a laptop is read moved the
  phones' version and would have recomputed their readings for nothing.
- **Prose is deliberately not fingerprinted.** A `why` lives inside the ruleset literal and
  editing one changes nothing about what comes out of a reading. Rewriting a comment should
  not recompute three thousand rows.
- **The version covers the code and not the vocabulary**, and this is the part that is easy
  to miss. A reading is a function of the rules *and* of the words handed to them, and
  entering a hundred aliases in the registry moves no version at all — so nothing looks
  stale and nothing is recomputed. Registry work therefore has to be followed by a
  **re-read**, which reads what is stored with the reader as it is now and does not consult
  the version. A change to a maker's model names asks for one itself (`reread_requests`, see
  `app/features/brands/README.md`); other registries — colours, attribute names — still
  need a reparse or `POST /api/admin/brands/{id}/reread` by hand. Ordinary ingestion still does: there, unchanged bytes should not cost
  work, and that is what keeps `raw_offers` proportional to how much the world changes
  rather than to how often we look at it.

## Vocabulary is data, structure is code

- **A rule may not carry a shop's or a language's words.** That `Iekšējā atmiņa` means
  built-in storage is a Latvian fact and belongs in `attribute_aliases`, which has a
  `language` column for it; that built-in storage tells two phones apart and working memory
  does not is true in every language and belongs in the category's rules.
- The registries are the language tables: `attribute_aliases` and `attribute_value_aliases`,
  both keyed by a normalized string and a language, both nullable where the string belongs
  to no particular language — a maker's marketing name is the same word everywhere.
  `markets.languages` is ordered, and the first is the market's default.
- **Words a rule needs are handed in, never queried.** They arrive as a `Vocabulary`
  (`normalization/rules.py`), loaded by the caller and passed to `read()`, because reading is
  a pure function of a payload and the rules that apply to it — that purity is what lets a
  stored payload be read again and the two readings compared. A rule given no words does
  nothing, which is declining to guess, not a failure.
- Category names go this way, and so do attribute names: `category_aliases` and
  `attribute_aliases`, loaded once per category by `OfferService` and scoped to it, which is
  how a shop's `Telefons` is cut off the front of a title and its `Iekšējā atmiņa, GB` is
  known to be storage. A field name is resolved **exactly**, never by a fragment of it:
  `ram` inside `paRAMetri` once threw rdveikals' storage away as working memory. A name no
  row covers is not read — a new shop's field names are rows to enter, not a tuple to grow.
- **A value's words are rows too.** `Nē`, `Nav`, `Jā`, `Ir` are how four shops answer
  "has it a modem?", and they sit in `attribute_value_aliases` under connectivity, handed in
  as `Vocabulary.values`. A rule that treated every answer it could not parse as "no" read
  `Jā` as a Wi-Fi tablet. A word the registry does not know says nothing.
- **Where two sources disagree about an axis, the reading takes neither.** Title and field
  named different capacities 38 times in 5188, and the market sided with each about as
  often; ranking one over the other was wrong fifteen times or more. An empty axis sends a
  listing the slow way round, a wrong one files it under another product at confidence.
- Matching leans on the language-neutral signals on purpose — barcode, part number, model
  designation — so language is a question about attributes and the storefront, not about
  identifying a product.

- **A rule about the shop goes under the shop, a rule about how it names this category's
  products under the channel.** Barcodes, part numbers and stock words live in
  `normalization/shops/`, and a new category of the shop gets them on its first day; a
  model or a colour rule lives in `normalization/sources/`, and a new category starts
  without it, to be written against what it collects. When unsure, it belongs to the
  channel: a shop rule that turns out to be about phones is read into every other category.

## What a channel may decide, and what it may not

- A channel returns the **shop's own shapes**: its field names, its attribute labels, its
  codes as it listed them. Turning them into ours is a reading decision, done against stored
  bytes and re-runnable.
- **`schema.org/InStock` means the shop will sell the thing, not that it has it.** Four
  shops in a row now: dateks says it for all 745 while its own words call 524 to order,
  bm.market for 936 of 937 against an `availability_type` that says 934 are to order,
  euronics for all 319 including the 58 its listing marks `On order`, tet for all 40 sampled
  including the 3 it flags `Drīzumā`. Treat the field as decoration and find the shop's own
  word — it is on the listing card in three of those four. A channel that reads the markup
  reports a warehouse nobody has.
- In particular a channel does not choose which of a shop's numbers is a barcode.
  `normalization/barcodes.py` does, once, for every shop: check digits and GS1's reserved
  prefixes are a standard, not something a shop invented.
- `normalized_offers.attributes` holds the shop's own names untouched;
  `normalized_offers.identity` holds ours, canonical and parsed. Mixing them leaves no way to
  tell which is which.
