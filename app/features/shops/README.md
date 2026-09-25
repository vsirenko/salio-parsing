# shops

Who the buyer deals with, how we read their offers, and who is actually selling.

## Endpoints

| | |
|---|---|
| `GET · POST /api/admin/shop-groups` | one retail brand across countries, optional; rows count their shops |
| `GET · PATCH /api/admin/shop-groups/{group_id}` | read or rename one |
| `GET · POST /api/admin/shops` | list with counts and health — filter by `country_code`, `market_code` (with `market_state`: `shown` by default, `hidden`, `attached`), `is_marketplace`, `search`, `ids`, `health`; `?sort=` |
| `GET · PATCH /api/admin/shops/{shop_id}` | read or edit one |
| `GET /api/admin/shops/{shop_id}/markets` | where its offers are shown |
| `PUT · DELETE /api/admin/shops/{shop_id}/markets/{market_code}` | attach, enable, detach |
| `GET · POST /api/admin/shops/{shop_id}/sources` | how we read it |
| `GET · PATCH · DELETE /api/admin/sources/{source_id}` | one channel, its last run and next slot; delete only one that collected nothing |
| `GET · POST /api/admin/shops/{shop_id}/sellers` | who is selling inside it |
| `PATCH /api/admin/sellers/{seller_id}` | rename a seller |

No delete on a shop: offers and price history will point at it, and retiring one means
switching its markets off — which keeps the history instead of losing it.

## How it works

**Three entities that look like one and are not.**

- A **shop** is the commercial party a buyer deals with. It has a name, a logo, a rating
  among buyers, and it is what somebody picks on a card.
- A **source** is one way into a shop. Not the shop and not its website: a shop can have
  several, and they do not reach the same things. Its `trust` says how much that channel's
  data is worth, which has nothing to do with whether the shop is any good.
- A **seller** is who is actually selling. For an ordinary shop that is the shop itself;
  for a marketplace it is one of thousands of traders behind it.

**Why the split is not pedantry.** Give MediaMarkt both a feed and a scraper. If the seller
hung off the source, that one shop would become two sellers, the same listing two offers,
two lines in the price history and two shops on the card. With the split, both channels
converge on one offer and `raw_offer.source_id` remembers which saw it — which is also how a
barcode from the feed and a description from the page end up on the same row.

**A channel declares three things, and format is the least of them.**

| | |
|---|---|
| `access` | `wholesale` — one request returns everything; `retail` — a listing, then a request per product. This is what decides the schedule. |
| `decode` | `json_ld`, `embedded_state`, `graphql`, `private_api`, `xml`, `markup`. A swappable function and nothing more. |
| `delivers_full` / `delivers_quick` | which of `catalogue`, `price`, `availability` each pass actually brings back. |
| `category_id` | what it collects, when it collects one thing. Null for a channel carrying a whole shop. |

`category_id` is what selects a category's reading rules, and the reason it is on the channel
rather than inferred is that the same shape of value means different things to a laptop and a
monitor. Null is a real answer, not a missing one: a mixed feed has no single category, and
no rules at all is a quieter failure than the wrong ones.

`delivers_quick` is the one that is easy to get wrong and expensive to discover. Whether a
cheap pass carries stock is a property of the channel, not a general rule, and it decides
whether fresh availability costs a full crawl — a budget fact worth knowing before anything
is promised to a shopper. Two rules are enforced, in the service for a usable message and in
the database as the backstop: a quick pass cannot deliver what the full one does not, and a
wholesale channel has no quick pass at all, because one request is already everything.

Why the unit is a channel rather than a shop: two shops of one group can run the same search
engine behind the same code and differ only in which index is queried, one carrying barcodes
for every product and the other for none. Read as "a shop without barcodes", that sends
someone to parse titles for thousands of listings; read as a channel, the answer is a second
door into the same shop.

**A shop's country is not a market.** `country_code` points at `countries`: a German shop
delivering to Riga needs a row even though we run no German storefront. Where its offers
are *shown* is `shop_markets`, which points at `markets`.

**`shop_markets` carries its own flag.** Delivery is the reason a shop could appear in a
market; whether it does is our decision. A shop can be switched off in Lithuania without
being touched in Latvia, and it is attached disabled by default. So `?market_code=` alone
still means *shown there*, which is what every caller asked it before; the market card,
which has a switch per shop, asks `market_state=attached`, and a row carries both lists —
`markets` shown, `hidden_markets` attached and off — so the switch knows its position.

**An ordinary shop gets its seller created with it**, named after the shop. Price history is
keyed by seller, so an offer cannot attach to anything without one — leaving it to a second
call means somebody forgets and the first crawl has nowhere to put its prices.

**A shop row says what it holds.** `sources_count`, `sellers_count`; `offers_count` is its
listings **on sale** — the same test as everywhere (`offer_is_listed`: no ok full pass of the
listing's channel began after it was last seen); `products_count` is the products its new,
on-sale, placed listings sit on, which is what a buyer would find it on. `markets` are the
enabled ones, `hidden_markets` the attached ones switched off, `group` is `{id, name}` so a table prints it without a second request.

**Health is about the catalogue, so only full passes count.** Per enabled channel the
newest full pass that ended `ok` or broke (`failed`, `rejected`, `interrupted`) decides —
a run still going, or one that was skipped, says nothing yet. The shop is `failing` when any
enabled channel's newest such pass broke, `never` when none has a sound one (a new shop, or
every channel disabled), and `ok` otherwise. `last_full_ok_at` is the newest good full pass
across its channels and is kept while a later one fails: "broken since" is what a person
reading the row needs. A quick pass breaking does not make a shop failing — prices go
stale, the catalogue does not.

**A channel shows its last run and its next slot.** `last_run` is the newest run of any
kind; `next_full_at` and `next_quick_at` are computed from the cron with the scheduler's own
function (`app/core/schedule.py`), and are null on a disabled channel, because nothing will
run it. `offers_count` is the on-sale listings this channel has observed; with two channels
into one shop the two counts overlap, and the shop's count is not their sum.

## Decisions worth knowing before changing it

- **A channel is deleted only while it has collected nothing** — no observations, no runs;
  otherwise 409 `source_has_history`. One that has run is retired with
  `is_enabled=false`: its observations are the listings' history and their readings, and a
  delete would take them with it. The delete is for a channel added by mistake.
- **A seller's name is editable, its `external_id` is not.** That is how a marketplace
  names the trader in its feed, and changing it would file the next crawl's listings under
  a new seller.
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
