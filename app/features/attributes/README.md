# attributes

One canonical registry of attributes, because sources name the same thing a dozen ways.

## Endpoints

| | |
|---|---|
| `GET · POST /api/admin/attributes` | the registry |
| `GET /api/admin/attributes/{attribute_id}` | one attribute |
| `GET · POST /api/admin/attributes/{attribute_id}/aliases` | what the sources call it |
| `GET · POST /api/admin/attributes/{attribute_id}/values` | canonical values, enums only |
| `POST /api/admin/attributes/values/{value_id}/aliases` | what the sources call a value |
| `GET /api/admin/attributes/by-category/{category_id}` | what a category makes of them |
| `POST /api/admin/categories/{category_id}/attributes` | attach one to a category |
| `PATCH · DELETE /api/admin/categories/{category_id}/attributes/{attribute_id}` | adjust or detach |

## How it works

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
- **Turning `identity_bearing` on or off invalidates every identity key in that category** and
  requires re-matching it. That is an operation the size of a migration, not a checkbox.
- The candidate queues that turn an unknown string into a mapping are not built: they are
  filled by ingestion, which does not exist yet.

See also `docs/parser-design.md`, "One canon, and everything normalized onto it".
