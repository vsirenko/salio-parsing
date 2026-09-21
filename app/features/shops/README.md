# shops

Who the buyer deals with, how we read their offers, and who is actually selling.

## Endpoints

| | |
|---|---|
| `GET · POST /api/admin/shop-groups` | one retail brand across countries, optional |
| `GET · POST /api/admin/shops` | list and create — filter by `country_code`, `market_code`, `is_marketplace` |
| `GET · PATCH /api/admin/shops/{shop_id}` | read or edit one |
| `GET /api/admin/shops/{shop_id}/markets` | where its offers are shown |
| `PUT · DELETE /api/admin/shops/{shop_id}/markets/{market_code}` | attach, enable, detach |
| `GET · POST /api/admin/shops/{shop_id}/sources` | how we read it |
| `PATCH /api/admin/sources/{source_id}` | edit a source |
| `GET · POST /api/admin/shops/{shop_id}/sellers` | who is selling inside it |

No delete on a shop: offers and price history will point at it, and retiring one means
switching its markets off — which keeps the history instead of losing it.

## How it works

**Three entities that look like one and are not.**

- A **shop** is the commercial party a buyer deals with. It has a name, a logo, a rating
  among buyers, and it is what somebody picks on a card.
- A **source** is the channel we read bytes through — a feed, an API, a scraped site. Its
  `trust` says how much that channel's data is worth, which has nothing to do with whether
  the shop is any good.
- A **seller** is who is actually selling. For an ordinary shop that is the shop itself;
  for a marketplace it is one of thousands of traders behind it.

**Why the split is not pedantry.** Give MediaMarkt both a feed and a scraper. If the seller
hung off the source, that one shop would become two sellers, the same listing two offers,
two lines in the price history and two shops on the card. With the split, both channels
converge on one offer and `raw_offer.source_id` remembers which saw it — which is also how a
barcode from the feed and a description from the page end up on the same row.

**A shop's country is not a market.** `country_code` points at `countries`: a German shop
delivering to Riga needs a row even though we run no German storefront. Where its offers
are *shown* is `shop_markets`, which points at `markets`.

**`shop_markets` carries its own flag.** Delivery is the reason a shop could appear in a
market; whether it does is our decision. A shop can be switched off in Lithuania without
being touched in Latvia, and it is attached disabled by default.

**An ordinary shop gets its seller created with it**, named after the shop. Price history is
keyed by seller, so an offer cannot attach to anything without one — leaving it to a second
call means somebody forgets and the first crawl has nowhere to put its prices.

## Decisions worth knowing before changing it

- **`is_marketplace` is not editable.** Turning it off would strand the traders a
  marketplace has; turning it on would leave an ordinary shop's single seller looking like
  a trader. Either way the price history stops meaning what it says.
- **Adding a seller to a non-marketplace is refused.** Several sellers in a shop that has
  one would put several price lines where there is one.
- **The same trader on two marketplaces is deliberately not modelled.** That is a second
  identity problem and it buys nothing for comparing prices; a seller is scoped to its shop
  and stays there.
- `trust` on a source and `rating` on a shop look similar and must not be merged: one is
  how much we believe the data, the other is what buyers think of the service.

See also `docs/parser-design.md`, "Markets, shops and where money is charged".
