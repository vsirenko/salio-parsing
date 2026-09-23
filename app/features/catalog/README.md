# catalog

The family a human searches for, the thing that is bought, and what is known about it.

Product and variant live in one feature because they are two levels of one thing: a title,
a slug and an identity key are all derived across both, and neither is meaningful without
the other. `users`, which holds accounts and sessions, is the same shape.

## Endpoints

| | |
|---|---|
| `GET · POST /api/admin/products` | list and create families |
| `GET · PATCH /api/admin/products/{product_id}` | read or correct one |
| `GET · POST /api/admin/variants` | list and create — `identified` filters on whether a key could be computed |
| `GET · PATCH /api/admin/variants/{variant_id}` | read or correct one |
| `GET · PUT /api/admin/variants/{variant_id}/attributes` | what is known, and setting one |
| `DELETE /api/admin/variants/{variant_id}/attributes/{attribute_id}` | clear one |
| `GET · POST /api/admin/variants/{variant_id}/gtins` | barcodes |
| `GET · POST /api/admin/variants/{variant_id}/mpns` | part numbers |

Write endpoints exist because the matcher does not yet and nothing else can create a row.
Once it does, most of this becomes read-and-correct rather than create.

## How it works

**A variant is the primary entity.** It is what is bought, what carries a barcode, and what
an offer will attach to. An offer linked at product level would put the price of a 128 GB
phone in the same history as the 1 TB one. A product is a grouping with no price and no
barcode, and it is allowed to contain exactly one variant — a book has no variations, and
inventing a hierarchy where the category has none would be worse than the duplication.

**`variant.product_id` is nullable.** A variant created from an offer that matched nothing
does not belong to a family yet; grouping it from a single data point would be a guess and
is a later, cheaper decision.

**Three derived values, and one rule for all of them.** The title, the slug and the identity
key are recomputed from their inputs whenever any of those change — never edited in place.
What a human wants to pin lives in an `*_override` column beside the derived value, so a
correction survives the next regeneration rather than being flattened by it.

- **Title** is brand, model, then the identity-bearing values in `category_attribute.position`
  order. The field that orders the filters also orders the words, because the order that
  reads well in a list reads well in a name.
- **Slug** is the title with the id appended. Nobody hand-names a million rows, and the tail
  means a retitle does not break the link.
- **Identity key** is a hash of brand, category, normalized model, kind, unit count and the
  identity-bearing values — **but only when every one of them is present.**

**That last condition is the whole safety of the mechanism.** A key built from a partial set
would be equal for two different things that happen to share the attributes that *were*
extracted, and it would merge them confidently. Missing one axis leaves the key null and the
variant takes the long way round through the matcher: slow rather than wrong.

Brand and category are in the hash because without them a phone and a tablet with the same
colour and storage would collide.

## Decisions worth knowing before changing it

- **Barcodes and part numbers are plural.** Regional packaging and a change of supplier both
  give one variant another barcode; a single column would look obvious and become a lie
  within a month. `variant_mpns` repeats `brand_id` so the blocking index spans the pair —
  a part number only means something beside its maker.
- **`model_normalized` strips everything that is not a letter or a digit**, which makes it
  language-neutral. That is the point: a Latvian, Lithuanian and Estonian title share almost
  nothing except the brand and the model.
- **Except `+`, which becomes `plus`.** Dropped, it gave `Galaxy S26+` and `Galaxy S26` one
  form and so one identity key, and by the time that was noticed 111 listings on 40 entries
  were filed under the other phone — first by the model rung, then by the barcodes those
  entries learned from it. Spelled out rather than kept, because `Galaxy S25+` and `Galaxy
  S25 Plus` are one phone written two ways. Changing this function changes every stored
  form: `tools/replus.py` is how the last change was carried through, and the next one needs
  the same.
- **A number is stored in its attribute's unit and written in a person's.** Storage is
  megabytes, which is right for the key and the filters, and a title printed it that way:
  `OnePlus 10T 131072 black` named 2235 of 2400 entries until 23.09.2026.
  `identity.display_number` writes megabytes in the largest binary unit (`128 GB`, `1 TB`)
  and inches with a `"`; the key is built from the stored value and does not see it.
- **A value's type is checked in the service**, because `attributes.value_type` and the
  value columns are in different tables and no constraint spans them. A number stored as
  text would be invisible to every range filter and would silently drop out of the key.
- **`image_url` is a link to somebody else's CDN.** It rots when that shop removes the file,
  and it hotlinks. Storing the image ourselves is the real answer and there is no file
  storage yet — see `TODO.md`.
- **`description` is declared and nothing fills it.** Deliberate: it is not yet decided
  whether anything will.
- **No delete and no merge.** A merge moves offers and price history with it, and neither
  exists; building it now would be guessing at its hardest part. The `variant_merges` and
  `product_merges` tables are in place so that when it arrives, an id survives being merged
  away and an external link does not rot.

See also `docs/parser-design.md`, "The two levels, and why both".
