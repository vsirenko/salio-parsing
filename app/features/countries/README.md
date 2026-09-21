# countries

Every country we need to be able to describe — which is not the same set as the countries we
sell in.

## Endpoints

| | |
|---|---|
| `GET /api/admin/countries` | list, filterable by `is_eu` |
| `POST /api/admin/countries` | add one, as shops from it start appearing |
| `GET · PATCH /api/admin/countries/{code}` | read or edit — mainly the VAT rate |

No delete: a country a shop already points at cannot go, and one nothing points at costs
nothing to keep.

## How it works

**A country is not a market.** A shop in Germany may deliver to Riga while we run no German
storefront at all, so Germany needs a row here — for its VAT rate and for the shop to point
at. The storefronts we run are [markets](../markets/README.md).

The split follows the fields: a VAT rate and a currency are facts about the world and live
here; a language and an enabled flag are decisions about a storefront and live on the market.

**The VAT rate is a fraction, not a percentage** — `0.2100`, not `21` — and the database
enforces it is one. It is only ever multiplied; storing percentages scatters a division by a
hundred through the code until one of them is forgotten.

**The rate is nullable, and null means unknown.** Nothing is computed from it — prices are
stored exactly as the buyer sees them — so a rate only ever *explains* why two prices differ.
A wrong one explains it wrongly and silently, which is worse than a missing one. An explicit
null is accepted on update, so a wrong rate can be withdrawn rather than replaced by another
guess.

## Decisions worth knowing before changing it

- Only EUR and the three Baltic markets are seeded. Writing the currency and EU membership of
  thirty countries would assert facts that move — Bulgaria's euro adoption being the live
  example — and a wrong fact in reference data is believed. Others come through the POST,
  which keeps that data rather than a release.
- The rate is current, not historical. Rates change, and when one does this column is updated
  and past explanations quietly become wrong. That is acceptable only while no arithmetic
  depends on it; the day it does, this becomes a table with `valid_from`.
- One standard rate, though reduced rates exist for food and books. Same reasoning: we
  explain, we do not compute.
- `is_eu` is not decoration. Customs, duty and the cross-border VAT rules all differ across
  that line, so what can be promised to a buyer differs with it.

See also `.claude/rules/database.md`.
