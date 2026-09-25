# attributes

One canonical registry of attributes, because sources name the same thing a dozen ways.

## Endpoints

| | |
|---|---|
| `GET · POST /api/admin/attributes` | the registry, with counts, `search`, `ids`, `?sort=` |
| `GET · PATCH /api/admin/attributes/{attribute_id}` | one attribute; rename and relabel it |
| `GET /api/admin/attributes/{attribute_id}/categories` | the categories it is bound to |
| `GET /api/admin/attributes/{attribute_id}/resolve` | what the registry makes of a string |
| `GET · POST /api/admin/attributes/{attribute_id}/aliases` | what the sources call it |
| `DELETE /api/admin/attributes/{attribute_id}/aliases/{alias_id}` | stop reading a name as it |
| `GET · POST · DELETE /api/admin/attributes/{attribute_id}/dismissals` | words a shop writes that are deliberately none of its values |
| `GET · POST /api/admin/attributes/{attribute_id}/values` | canonical values, enums only |
| `PATCH · DELETE /api/admin/attributes/values/{value_id}` | reorder or relabel a value; remove one nothing carries |
| `POST /api/admin/attributes/values/{value_id}/aliases` | what the sources call a value |
| `DELETE /api/admin/attributes/values/{value_id}/aliases/{alias_id}` | stop reading a word as it |
| `GET /api/admin/attributes/by-category/{category_id}` | what a category makes of them |
| `POST /api/admin/categories/{category_id}/attributes` | attach one to a category |
| `PATCH · DELETE /api/admin/categories/{category_id}/attributes/{attribute_id}` | adjust or detach |

## How it works

**A label is what a person reads; a name and a canonical string are what the system
keeps.** `labels` on an attribute and on a value is text by language — `{"lv": "Operatīvā
atmiņa", "ru": "Оперативная память"}`, `black` as `melns` — and nothing reads it but a page.
So the two things a front end might want to edit are fixed on purpose. **The key** is how
the readings and the rules name the attribute. **A value's canonical string** is what a
reading produces and the matcher looks up — `wifi`, `Intel Core Ultra 5 226V` — and renamed,
the next reading would produce the old string and find nothing. A value that reads badly
gets a label.

**What changes, and what does not, once something is stored.** The unit and the scale of a
number attribute change only while no entry holds a value: `storage_mb` holds `16384`, and
calling the unit GB under it would make every stored value a thousand times larger. A value
is removed only while no entry carries it (409 `value_in_use` otherwise, with the count):
one that is carried is part of those entries' identity keys, and folding it into another is
a merge of entries, which is the matcher's to do, not an edit here.

**A word can be marked as none of the values.** `melna, pelēka` in a colour field is two
colours, and not resolving it is right: a product filed under one of them is filed wrong. A
dismissal takes it off `GET /api/admin/offers/unresolved-colours`, which computes everything
else it shows; the word is kept casefolded and trimmed, as that list groups it, and deleted
by query because what shops write has slashes in it.

**`resolve` answers what a reading would**: whether the string is a name a shop gives the
attribute, and which value it resolves to, by its canonical spelling or an alias, compared
in the normalized form the registry stores. A colour's readings also try phrases of a title;
this is the string as given.

**A row counts where an attribute is used and how far it is set up** — categories, values,
aliases, entries carrying a value — and a value, the entries that carry it: a value nothing
carries and no reading produces is one to look at.

**A category's binding names its attribute** — `attribute: {id, key, name, value_type,
unit_dimension}` beside `attribute_id` — so a table of them prints `RAM` without loading
every attribute to look it up.

**One registry, used per category.** `Цвет`, `Color`, `Krāsa` and `Spalva` all resolve to
one attribute, which is what makes a feed param and a phrase cut out of a title
interchangeable: once both become `capacity = 256 GB`, where the value came from stops
mattering downstream.

The type, unit dimension and rounding scale belong to the attribute. `identity_bearing`
belongs to the **pairing** with a category, because the answer genuinely differs — weight is
an axis for food, where 500 g and 1 kg are different products, and a specification for a
washing machine. `label_override` and `display_unit` are per pairing for the same reason.

**Normalization is a function; a declension is a row.** Case, surrounding punctuation, `®`
and trailing colons are computed away, so `Krāsa`, `krāsa` and `Krāsa:` are one alias rather
than three. What no rule derives is a row: `Samsungo → Samsung` is a fact somebody
established, and Lithuanian declines foreign names as grammar.

**Numbers are parsed, enums are looked up.** A number is read out of its string, converted to
the base unit and rounded to the attribute's `scale` — which is also what keeps an identity
key stable, since without a fixed scale `39.624` and `39.62` describe one screen and hash to
two keys. Only enums have canonical values, so capacity, weight and screen size generate no
mapping work at all.

## Decisions worth knowing before changing it

- **An alias is unique per attribute, not globally.** `Размер` is a real name for both shoe
  size and clothing size; which one an offer means is settled by the category it landed in.
- **A value alias is unique per attribute rather than per value**, so one spelling cannot
  resolve to two values of the same attribute. That is why `attribute_id` is repeated on the
  row.
- **Free text cannot carry identity**, and this is enforced in the service rather than the
  database: `value_type` sits on the attribute and `identity_bearing` on the pairing, so no
  constraint spans them. It matters — "Black matte" and "black, matte" are one product and
  two keys, and an unstable key is worse than none because it confidently separates things
  that are the same.
- An attribute is *one* attribute only if its values mean the same thing everywhere. Size 42
  in shoes and size 42 in clothing are different scales, so they are two.
- Defining attributes inside each category was the alternative and is worse: every alias and
  every value would be repeated per category, a cross-category facet would be impossible, and
  the mapping queue would never drain.
- **A value can be kept out of titles and still be in keys.** `in_title = false` is for a
  value nearly every entry carries: the glass is `standard` on every tablet and laptop but
  Apple's nano-texture ones, and a title would only repeat it. Titles written before a
  change keep what they said until their entries are next regenerated.
- **Turning `identity_bearing` on or off invalidates every identity key in that category** and
  requires re-matching it. That is an operation the size of a migration, not a checkbox.
- The candidate queues that turn an unknown string into a mapping are not built: they are
  filled by ingestion, which does not exist yet.

See also `docs/parser-design.md`, "One canon, and everything normalized onto it".
