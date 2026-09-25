# Footwear: what three shops serve, and what it would take to compare them

Research of 24.09.2026, before anything is built. Measured against the live sites, a handful
of pages each; the counts are the shops' own. Nothing here is collected or stored yet.

Shops looked at: **About You** (aboutyou.lv), **Zalando** (zalando.lv), **eapavi**
(eapavi.lv, the eobuwie / Modivo group — the same platform as eschuhe.de, obuvki.bg and
others).

## The question that started it

Whether TypeSafe can match shoes by photo, because shops do not always give every field.
**It cannot**: its docs say "Jev accepts text only … Images, audio, and video are not
supported (yet)"; `state` is a string or JSON. And, measured below, photos are not needed:
all three shops publish a barcode for every size.

## One pair, three shops

The same product was found on all three and confirmed by barcodes, not by name:

- About You `30557422` and Zalando `PU115P014-A13` — Puma King Indoor, white/black. All 10
  of About You's EANs are among Zalando's 18.
- eapavi `401683-02` (two cards, `-w` and `-m`) and Zalando `PU115P014-A11` — Puma King
  Indoor, white/frosted ivory. EANs match.

What each shop wrote for them:

| | About You | Zalando | eapavi |
|---|---|---|---|
| structured data | JSON-LD `ProductGroup`, a variant per size | JSON-LD `ProductGroup`, a variant per size | JSON-LD `ProductGroup`, a variant per size |
| barcode | EAN per size (`offers.gtin`) | EAN per size (`gtin`) | EAN per size (`gtin13`) |
| name | `Zemie brīvā laika apavi 'King'` | `KING INDOOR UNISEX - Futbola apavi iekštelpām - white/black` | `Snīkeri Puma King Indoor 401683 02 W Balts` |
| colour | `balts` | `white/black/balts` (maker's name + Latvian word) | `Balts` |
| sizes | 10: `37`, `39-39,5`, `43-43,5` … | 18: `37`, `37.5`, `39` … | 9 + 8, split into a women's and a men's card |
| article number | its own, `PUM9wo0004000001` | its own, `PU115P014-A13…` | **the maker's**, `401683 02` (model + colourway), in the name and the URL |
| price, all sizes | 57.90 € | 53.95 € | 56.99 € |

What follows from it:

- **The barcode settles it**, per size, across all three. It is the only signal all three
  share.
- **Without it the match fails.** The model is named `King` at one shop and `King Indoor`
  at another; both white colourways of it are `balts`. A model rung would miss or be
  ambiguous, and a colour rung would confidently join two colourways.
- **Only eapavi carries the maker's style code.** It is the brand + part number rung for a
  listing without a barcode; About You and Zalando number products their own way, so their
  article numbers cannot meet anyone else's.
- **Sizes are written differently.** `39-39,5` at About You is `39` at Zalando — one EAN.
  Only a listing with no barcode needs them reconciled, and that is a table (EU, UK, US, cm,
  men's and women's scales), which is registry data rather than rules.
- **Colour between shops is not evidence.** Two different colourways were both `balts`.

A trap met on the way: Zalando prints one EAN (`4069157121330`) on all ten King Indoor
pages, in a carousel of other colourways. A barcode must be read from the product's own
variants in its `ProductGroup`, never from anywhere on the page.

## Reaching them

The first attempts suggested a browser was needed. It is not.

- **eapavi** answers a plain HTTP request; the `ProductGroup` is server-rendered in the HTML.
- **About You and Zalando check the TLS fingerprint.** A plain `curl` or `httpx` gets a shell
  without the product (About You) or a 403 (Zalando). The same request carrying a Chrome
  fingerprint — `curl_cffi` with `impersonate="chrome"` — gets the full server-rendered page:
  About You's product page with its `ProductGroup` and 10 EANs, Zalando's with 18 variants.
- About You also loads products over gRPC-web
  (`tadarida-web.aboutyou.com/aysa_api.services.article_detail_page.v1.ArticleDetailService/GetProductBulk`,
  binary protobuf with no published schema) and has an older `api-cloud.aboutyou.de`, which
  Cloudflare refuses. Neither is needed: the server-rendered page carries everything.
- That fingerprint check is a bot defence the shops put there on purpose. Getting past it
  works technically; the shops' terms and our request rate are what to look at before a full
  crawl.

Finding every product:

| | how | per page |
|---|---|---|
| About You | `robots.txt` → `sitemap/lv/sitemap-index.xml` → 7 `sitemap-product-N.txt`, 50 000 URLs each, 320 379 products in all | — (`?page=2` on a category returned page 1 again; the rest loads over gRPC) |
| Zalando | category listing, `?p=N` | 24 |
| eapavi | category listing, `?p=N` (`/c/sieviesu`, `/c/viriesu`, `/c/bernu`) | 72 |

## How much, and what it costs

| | shoes | one product page | one channel at our politeness |
|---|---|---|---|
| About You | ~25 000 (URLs with a footwear word in their slug, from the sitemap; approximate) | 0.3 s, ~0.9 MB | ~55 min |
| Zalando | ~51 000 (women 29 364, men 12 677, children 9 043; unisex may repeat) | 0.8 s, ~1.8 MB | ~1 h 55 min, plus ~2 100 listing pages |
| eapavi | ~56 000 (women ~30 400, men ~13 100, children ~12 300, from page counts) | 0.7 s, ~0.9 MB | ~2 h, plus ~780 listing pages |
| **all** | **~132 000** | | **~2 h** with the channels side by side |

At the rate every channel already keeps — six open, eight a second — each shop reads at
about eight products a second; a product is one request, because all its sizes are on it.

- **Transfer**: ~170 GB a pass decompressed; compressed an estimate, not measured, of
  20–25 GB. A daily full pass is ~600–750 GB a month, which an ordinary VPS carries for
  €10–20.
- **Disk**: a snapshot of the whole page, as the store keeps now, is ~20 GB a pass; keeping
  only the JSON-LD is a few kilobytes a product.
- **Proxies** are the one thing that would be expensive: residential traffic is €3–10 a GB,
  €60–250 a full pass. Avoided by staying polite and not crawling everything often.
- **The judge** is hardly needed: the barcode does the matching.

Cheaper still: prices from the listing pages (~2 900 pages at Zalando and eapavi, minutes
rather than hours), the full product pass every few days for new products and barcodes.

## What a listing page carries, and when the product page is still needed

A barcode and a style code never change, so a product page is needed once, when the product
first appears. Price, stock and sizes do change — and the question that decides the daily
cost is whether the listing pages carry them. Checked product by product against the
product pages' own `ProductGroup`:

| | price | sizes in stock | colour | per request |
|---|---|---|---|---|
| **Zalando** | yes, equal to the card's on 6 of 6 | **yes, exactly** — the listing's `simples` equalled the card's in-stock sizes on 6 of 6 | in the name (`… - dark grey`) | 24 products, 0.6 s |
| **eapavi** | yes (`final`, `regular`, `minimal`) | **yes, exactly, with quantities** — not in the visible card text (which lists sizes only when five or fewer are in stock), but in the page's `productsAnalytics` state; equal to the product page on 150 of 150 (see *eapavi in full*) | in the name (`Snīkeri · Balts`) and a hex colour | 72 products, 1.3 s |
| **About You** | — | — | — | no listing path: the server renders the first 31 products of a category and `?page=`, `?p=`, `?offset=` all return them again; the rest loads over gRPC |

Where a listing does list sizes it lists them in its own spelling: `38.5` on eapavi's listing
is `38_1_2` on its product page — one size, and a table to reconcile.

So, per day:

- **Zalando**: listing pages only — price and exact size availability for everything, ~2 100
  pages, minutes — plus the product page of anything new, once, for its barcodes.
- **eapavi**: listing pages only — price, every size in stock and how many pairs of it, for
  everything, ~850 pages, minutes — plus the product page of anything new, and of a product
  when a size appears that has no barcode yet. See *eapavi in full*.
- **About You**: with its agreement, every shoe category through the site's own scroll
  stream, ~1 400 requests, minutes — sizes in stock for everything — plus the product page of
  anything new; product pages daily (~29 000, an hour) only if the per-size price is wanted.
  See *About You in full*. It is also most of the daily traffic (~22 GB decompressed, against ~2–3 GB
  for either of the others).

Zalando's GraphQL (`POST /api/graphql/`) was looked at as a faster way in and is not one. It
accepts only persisted queries by hash — ad-hoc queries and introspection are refused with
`not accepting GraphQL and no id found` — and none of the hashes its front end uses returns a
barcode: the product page loads its data server-side, and its only GraphQL call is the
wishlist. The hashes that exist return a product card (price, sizes in stock) and a product's
whole family of colourways with prices, a batch of ~30 per request, from a plain request with
a Chrome TLS fingerprint and the `frsx` cookie as `x-xsrf-token`. They change when Zalando
ships a new front end, which is why the listing HTML is the path to build on.

## What an offer should be

Recommended: **an offer is a shop's model in one colourway; its sizes are availability inside
it.** Not an offer per size.

- Price did not depend on size on any page looked at, so a price series per size would be
  ten rows of the same number — ~1.3 million offers and their histories instead of ~132 000.
- Every shop already cuts its catalogue by colourway: one URL, one colourway.
- What a buyer needs per size is whether it is in stock, which is current state on the
  offer; the price history stays one per offer.
- Every size's barcode goes onto the one catalogue entry, so the barcode rung fires on any of
  them — which is exactly how the About You and Zalando pair was found.

So a catalogue entry is a model in a colourway, holding many barcodes, and size is **not** an
identity axis, unlike a phone's storage. Two colourways are two entries, told apart by barcode
or style code — never by the colour word.

Two things to handle:

1. eapavi splits one colourway into a women's and a men's card. Two offers of one shop on one
   entry; a product card should show them as one shop with a range of sizes.
2. A price can differ by size — the last pairs of a size on sale. The offer then carries a
   "from" price over the sizes in stock, and the per-size prices stay in the reading.

## eapavi in full

Measured on 24.09.2026 against the live site: 9 listing pages (the first and a deep page of
each shoe section, and the catalogue root) and **150 product pages drawn at random** from
them, one request at a time with 0.7 s between. Every request answered 200, in 0.5–1.9 s;
nothing throttled or challenged.

**The catalogue.** 71 473 products under `/c/eapavi`, in seven roots:

| root | products | what it holds |
|---|---|---|
| Sieviešu (women) | 30 378 | shoes only — 21 sub-categories, from sneakers (none of them bags) to rubber boots |
| Vīriešu (men) | 13 063 | shoes |
| Bērnu (children) | 12 308 | shoes |
| Sports | 4 585 | shoes (hiking, football, running …) that also sit in the sections above |
| Unisex | 774 | also listed under women and men |
| Rokassomas (bags) | 8 386 | a root of its own |
| Aksesuāri (accessories) | 7 880 | a root of its own |

So the open question of how much of the women's, men's and children's sections is shoes has
an answer: all of it — bags and accessories are separate roots. The shoe roots overlap (21
products appeared twice in the nine pages), so a product is followed by its `sku`, never by
the section it was found in. **About 55 000 distinct shoes** (the catalogue less bags and
accessories).

**What `robots.txt` allows.** No sitemap is declared and none answers at the usual paths
(`/sitemap.xml` is a 404). Disallowed: the internal APIs (`/m-api/`, `/t-api/`, `/n-api/`),
filter combinations (`/c/*:*:*:*`, `/c/*:*-*-*`), `?orderDir` sorting, the account pages.
So the path is the category listing in the site's default order, and the product page — both
server-rendered HTML.

**A listing page** (`/c/<root>?p=N`, 72 products, ~250 KB compressed, ~1.3 s) is a Nuxt page;
its data is `window.__NUXT__`, an expression that evaluates to the page state (evaluated here
in an isolated `vm` context with no globals). Per product, in `data[0].products[]`:

- `sku` — 13 digits, the shop's product id, also the end of the product URL;
- `designSystem.brand`, `designSystem.name` (`Snīkeri · NB 740 · Balts` — type · series ·
  colour), `designSystem.color` (hex, 63 of 72), `designSystem.price` (`final`, `regular`,
  `minimal` — the 30-day lowest);
- `name` — the Polish full name, **which carries the maker's style code**:
  `Sneakersy New Balance GR740WM Biały`. The card's `model` appeared in it on 150 of 150;
- `colorVariantsLink.value` — the colourway group (`GR740`) and `colorVariantsCount`.

And in `state.search.category.productsAnalytics[]`, one entry per product on the page, **every
size of it**: the size code and label (`footwear_size`), **`stock_quantity`** and the per-size
offers with `price`, `final_price` and `omnibus_price`. Checked against the 150 product pages:

| | equal |
|---|---|
| the sizes a product has | 150 of 150 |
| which of them are in stock | **150 of 150** |
| the pairs in stock, size by size | 149 of 150 (one changed between the two requests) |
| the price of every size | 150 of 150 |

The visible `designSystem.sizes` is not that: it lists sizes only when five or fewer are in
stock and otherwise says `Pieejams vairākos izmēros` (58 and 92 of the 150); every product that
said so had six or more in stock, and four of the 58 lists named a size the product page did
not have in stock. Read the analytics block, not the visible text.

Not in the listing: the barcodes and the attributes. Every product listed had at least one
size in stock; a product sold out in every size seems to leave the listing, so its absence
from a full walk means "nothing in stock", and — as for every channel — only a collecting run
that ended ok may conclude it is gone.

**A product page** (`/p/<slug>-<sku>`, ~130 KB compressed, ~0.6 s) carries the `ProductGroup`
JSON-LD (per size: `gtin`, `size`, price, availability) and, in the same Nuxt state, much more
— `data[0].product`:

- `model` — the maker's style code, on **150 of 150**;
- `variants.<size>` — for each size its **EAN** (on **1 385 of 1 385** sizes), `stock_quantity`
  and offers; all offers in the sample came from the shop's own store (`EOB-LV`, `internal`) —
  no marketplace sellers;
- `values` — **124 attributes**: `kolor`, `main_color`, the maker's colour name
  (`kolor_nazwa_produktu`: `White`), the materials of upper, lining and sole, season, heel type
  and height, fastening, toe, gender, collection and series, technologies, country of origin,
  and `product_group_associated` (the colourway group, on 147 of 150).

**The price did not depend on the size on any of the 150** (1 385 sizes).

**Sizes** are written as whole numbers (`40`), halves (`38.5`, code `38_1_2`), thirds as the
French-point makers print them (`36 2/3`, `37 1/3`), and children's `18`–`35`. The listing and
the product page use the same labels, so nothing needs reconciling inside eapavi; a table is
needed only to compare a listing without a barcode with another shop.

**What it costs**, at the rate every channel keeps (six open, eight a second):

| pass | what | requests | time | transfer (compressed) |
|---|---|---|---|---|
| daily, listings only | every shoe root, every page | ~850 | **~2–3 min** (~18 min one at a time) | ~210 MB |
| first full pass | the listings, and every product page once | ~850 + ~55 000 | **~2 h** | ~7 GB |
| afterwards, daily | the listings, and the product page only of a new product or of a size without a barcode yet | ~850 + the new ones | minutes | ~210 MB + ~130 KB a new product |

So eapavi needs the product page once per product, for barcodes and attributes, and never
again for prices or sizes: **a daily walk of its listings gives every size in stock and how
many pairs, for all 55 000 shoes, in a few minutes.**

**Better still: the platform's search API** (used with eapavi's agreement; `robots.txt`
disallows the site's own `/m-api/`, `/t-api/`, `/n-api/`, and this is another host). When the
listing is paged in the browser, the page asks Modivo's search service for the products as
JSON:

`GET https://searchgcp.modivo.io/api/v5/search_web3?channel=eobuwie&currency=EUR&locale=lv_LV&limit=200&page=N&categories[]=<root>&support_aggregated_size_b=1&select[]=…`

- a plain GET — no session, no token, no fingerprint; `categories[]=eapavi` is the whole
  catalogue (71 416), `sieviesu` the women's shoes;
- `limit` up to **200** (250 and more answer 400); deep pages answer (`page=420` of 72);
- `select[]` picks the attributes returned: `model`, `manufacturer`, `kolor`,
  `nazwa_wyswietlana`, `product_group_associated`, `ean`, `footwear_size` …;
- each product carries `variants.<size>` with **the EAN, `stock_quantity` and the per-size
  offers and prices** — the product page's data, for 200 products a request;
- sort options include `created desc`, the way to find what is new.

Checked against the product pages read earlier: EANs equal on **290 of 290** sizes, the sizes
in stock on 30 of 32 products (the pages were read hours before — stock moved). A request of
200 is ~120 KB compressed and answers in about a second.

So **eapavi, daily, everything**: ~280 requests for the ~55 000 shoes (~360 for the whole
catalogue), **~5 min one at a time, ~35 MB** — barcodes, sizes, pairs in stock and prices,
with no product page at all. The product page stays only for what `select[]` cannot reach, if
anything; the listing HTML is the fallback when the API changes.

Two things to build it against:

- `productsAnalytics` is state the site keeps for its own tracking, not a published
  structure. A walk must fail loudly when a page arrives without it, or with products but no
  `variants`, rather than record every size as gone.
- One colourway is sometimes two cards (women's `-w`, men's `-m`); they are two offers on one
  entry, and the sizes of both belong to it.

## About You in full

Measured on 24.09.2026 against the live site with a Chrome TLS fingerprint (`curl_cffi`,
`impersonate="chrome"`): the robots file, the sitemaps, 21 category pages (the first page of
the women's, men's and children's shoe roots and of 14 shoe sub-categories drawn at random)
and **150 product pages drawn at random** from their 416 shoes, one request at a time with
0.8 s between. Every request answered 200, in 0.1–4.6 s (mostly under 1 s).

**What `robots.txt` allows.** Everything but the account pages and a list of query
parameters; the sitemap is declared. Two rules decide the path:

- a category listing may be read **only to page 3** (`page=1`, `2`, `3` are allowed and every
  other `page=` is disallowed), 30–32 products a page — so at most ~96 products of any
  category, and ~19 900 women's shoes cannot be walked through listings;
- the JSON state behind the pages (`/__/legacy_state?url=/p/…`, `…/c/…`) is disallowed.

So the path is the sitemap for discovery and the product page for everything else.

**The catalogue.** `sitemap-index.xml` → seven `sitemap-product-N.txt`, **320 379 product
URLs**, every product of the shop. Shoes by the shoe roots' own counts: women 19 937, men
8 028, children 15 814 over five age groups (2 532, 4 119, 3 350, 3 156, 2 657), which overlap
where a size range is shared. The sitemap does not say which URLs are shoes; the URL slug is
the product's Latvian name with the letters that carry diacritics dropped (`balerīnas` →
`baler-nas`, `čības` → `c-bas`), and these fragments matched **416 of the 416** shoes on the
category pages:

`apavi kurpes zabak sandal ies-cenes ieslucen cibas c-bas baler laivin snikeri espadril mokas
loferi puszabak botas tupeles celsijas sienamie sniega klasiskie-snorzabaki gumijas`

They match **~29 000 of the 320 379** sitemap URLs — the shoes to follow, give or take a few
hundred false hits (`sniega`, `gumijas` also name clothing), which the product page's own
category settles on first read.

**A category page** (~1.1 MB, a JSON state in `<script type="application/json"
data-tadarida-initial-state>` — the responses of their gRPC services, keyed by method):
`CategoryStreamService/GetProductStreamV2` holds the tiles, each with `productId`, the link,
the price and **`availableSizes`**, and `pagination.total`. The tile sizes equalled the
product page's sizes in stock on 147 of 150, and the tile price the product page's lowest on
150 of 150 — but only ~96 products per category are reachable, so the listing cannot be the
daily pass.

**A product page** (`/p/<brand>/<slug>-<id>`, ~0.9 MB decompressed, brotli on the wire, most
under 0.5 s) carries:

- the `ProductGroup` JSON-LD: `productGroupID` — **the maker's style code with its colour**
  (`15581-356` for a Rieker boot) on **150 of 150** — and per size an `Offer` with `gtin`, `mpn`
  (the shop's own article number, `RIEsf55001000001`), `sku` (the size's id), price and
  availability;
- the page state, `ArticleDetailService/GetProductBulk`: `product.sizes[]`, each with `id`
  (= the offer's `sku`), **`quantity`** (4, 22, 39 …), the shop size and the maker's size, the
  article number, `supplierId` and the size's own `price`.

A trap again, as at Zalando: `hasVariant` in the JSON-LD also carries the **other colourways**
of the group (4 261 variants on 150 pages against 1 649 sizes of the products themselves), some
without a URL. Join the JSON-LD to the page state by `sku` = size `id` and read only the sizes
the page state lists.

Checked on the 150:

| | |
|---|---|
| an EAN on every size (JSON-LD joined to the state) | **1 649 of 1 649**; every product 150 of 150 |
| the maker's style code (`productGroupID`) | 150 of 150 |
| `quantity` on every size | 150 of 150 |
| **the price differs by size** | **12 of 150** (8 %) — e.g. 47.70–63.90 € on one pair of shoes |
| sold out in every size | 2 of 150 |

A size out of stock carries no price. **Sizes** are written with a comma (`44,5`, `35,5`), and
some are two-dimensional — a length and a fit (`39 x Klasisks piegriezums`, `40 x Slim`), a
`$case` other than `singleDimension` in the state; children's sizes run from 18.

**What it costs**, at the rate every channel keeps (six open, eight a second), for the
~29 000 shoes:

| pass | what | requests | time | transfer |
|---|---|---|---|---|
| discovery | the seven product sitemaps | 7 | seconds | ~20 MB |
| daily, product pages | every shoe's product page — sizes, quantities, per-size prices | ~29 000 | ~1 h | ~26 GB decompressed; brotli, so a few GB on the wire (not measured) |
| **daily, the stream** (with About You's agreement) | every shoe root through `GetProductStreamPageV2` — sizes in stock, one price | ~1 400 | **~25 min, minutes in parallel** | ~100 MB |

Within its robots rules About You has no cheap pass for sizes: the listing that carries them
stops at page 3, and the state endpoint is disallowed.

**Past page 3, as the site itself loads it** (walked with About You's agreement). `?page=N` is
ignored — pages 2, 5 and 50 return page 1 — and `/__/legacy_state` returns an empty store. The
site loads the rest of a category as the visitor scrolls, from its gRPC-web service
`tadarida-web.aboutyou.com/aysa_api.services.category_page.v1.stream.CategoryStreamService/GetProductStreamPageV2`
(`application/grpc-web+proto`, binary protobuf with no published schema):

- the request carries a context the page builds (shop, build, A/B tests, a session id) and,
  in field 5, a **cursor token** the server issued — a base64 string
  (`CategoryStreamToken`: category, sort, start and end, filters);
- the first token is on the category page itself, `GetProductStreamV2.data.nextState`; every
  response carries the next one in its field 2, and the stream ends when none comes back;
- each response is 32 tiles (field 1 → 2 → 1): the product id in field 1 and **the sizes in
  stock** in field 10, the same `availableSizes` as on the first page.

Walked on 24.09.2026, one request at a time with 0.8 s between:

| | requests | products | time | transfer |
|---|---|---|---|---|
| men's premium shoes, to the end of the stream | 28 | 878 distinct of the 906 the category counts (97 %) | 28 s | 1.8 MB |
| women's shoes, the first 40 pages | 40 | 1 288 distinct | 40 s | 2.8 MB |

Every product came with its sizes (8.1 on average); against the product pages already read,
the sizes in stock were equal on **52 of the 54** products in both — one size back in stock in
the hour between the two reads, and one two-dimensional size (`39 x Klasisks piegriezums`)
the comparison left out. The 3 % the stream did not return is not explained yet (sold-out
products still counted, perhaps).

So About You **does have a cheap pass for sizes**: every shoe root walked through the stream,
~1 400 requests (women ~620, men ~250, children ~500 over overlapping age groups), **~25 min
one at a time or a few minutes with the roots side by side, ~100 MB a day**. It is an
internal protocol — the request is a captured template with the cursor swapped in — so a
walk must fail loudly when a response stops parsing, and the template needs refreshing when
the site ships a new build. The product page is still where the barcode and the per-size
price are: once for a new product, again when a size appears that has no barcode yet — or
daily, if the per-size price matters (8 % of pairs), since a tile carries one price.

## Zalando, measured

Measured on 24.09.2026 with a Chrome TLS fingerprint: the robots file, 7 listing pages and a
sample of product pages, one request every 2 s. **Zalando rate-limits hard**: after ~45 product
pages (plus the 7 listings) at that pace every request answered **429**, so 30 product pages
made it into the sample; the rest were not retried.

Its `robots.txt` shuts out AI crawlers by name (`ClaudeBot`, `GPTBot`, `Google-Extended` …,
`Disallow: /`); for everyone else it disallows `/api/*` except `/api/graphql/` and
`/api/navigation`, and URLs with four or more `&`.

**The catalogue.** Women's shoes (`/sievietem-apavi/`) 29 374, men's (`/viriesiem-apavi/`)
12 692, children's (`/berniem-apavi/`) 9 055 — **~51 000**. A listing page is 24 products,
server-rendered; the data is a GraphQL cache in `<script id="re-concurrent-data-hydrate">`
(`window.__hydrationDataConsume({...})`), each product with `sku` (Zalando's own,
`ME211N0UV-O11`), `name`, `uri`, `brand`, `displayPrice` and **`simples`** — the sizes, each
with its own sku. **Paging stops before the end**: `?p=300` answered, `?p=900` of women's
shoes (1 224 pages by the count) answered 400; the exact limit is not measured, so a full walk
has to cut the catalogue into sub-categories or filters that each stay under it.

**The product page** (~1.2–1.4 MB) carries a `ProductGroup` JSON-LD. On the 30:

| | |
|---|---|
| an EAN (`gtin`) on every size | **283 of 283** |
| the listing's `simples` equal the sizes in stock | **30 of 30** |
| **the price differs by size** | **6 of 30 (20 %)** — the listing carries one price |
| quantities per size | none — in stock or not |
| the maker's style code | none — `productGroupID` is Zalando's own sku |

So at Zalando the listing gives the sizes in stock exactly and the product page the barcodes
and the per-size price (which it uses often).

**The same listing through GraphQL, without the paging limit** (with Zalando's agreement;
`robots.txt` allows `/api/graphql/`). The listing page is itself built from persisted GraphQL
queries, and their ids and variables are in its own cache:

- the catalogue, `d160df72…` — a Relay connection over `ern:collection:cat:categ:<category>`
  with `first` and `after`. `after` is base64 of `[offset, seed]`, so any depth can be asked
  for directly: offset 30 000 of the women's shoes answered, where the HTML stops before page
  900. **`first` up to 200** (500 answers an error). It returns the product ids, `totalCount`
  and `pageInfo`;
- the product tile, `f2f27235…`, per `ern:product::<sku>` — name, brand, `displayPrice` and
  **`simples`** (the sizes in stock, each with its sku). Requests batch as a JSON array of
  operations: **50 in one request** answered (0.4 s, ~575 KB), 84 did not; dropping the gallery
  from the variables drops the sizes too.

A plain POST with a Chrome TLS fingerprint and the `frsx` cookie of any page as
`x-xsrf-token`. The sizes equalled the listing HTML's on 22 of 24 (read an hour apart). By
GraphQL's own counts: women 30 820, men 13 117, children 9 552 — **~53 500**. A browser driven
by automation gets nothing: Zalando's bot protection answers its own `/api/*` calls with 403
and renders no product.

So **Zalando, daily, every size in stock**: ~270 catalogue requests of 200 plus ~1 070 tile
batches of 50, **~1 350 requests, ~20–25 min at one a second**, ~600 MB decompressed. Still
one price per product and no barcode — those stay on the product page, once for a new product
and again when a size appears with no barcode yet; the per-size price (20 % of pairs) only
there. The sustainable rate is the open number: the HTML met 429 after ~50 requests at one
every 2 s, the GraphQL calls here were a dozen. Zalando's partner feed remains the way worth
asking for.

## Three shops side by side

| | eapavi | About You | Zalando |
|---|---|---|---|
| shoes | ~55 000 | ~29 000–44 000 | ~53 500 |
| EAN on every size | yes (100 %) | yes (100 %) | yes (100 %) |
| maker's style code | yes (`model`) | yes (`productGroupID`) | no |
| price differs by size | never (0 of 150) | 8 % | 20 % |
| pairs in stock | exact counts | exact counts | in stock or not |
| daily path to every size | search API, ~280 requests, ~5 min | category scroll stream, ~1 400 requests, ~25 min | GraphQL catalogue + tile batches, ~1 350 requests, ~20–25 min |
| barcodes | in the same API | product page, once per new product | product page, once per new product |

## Open, and the next step

- **How often the price differs by size** — at eapavi never (150 products, 1 385 sizes); at
  About You on 12 of 150 (8 %); at Zalando on 6 of 30 (20 %).
- **How often a barcode and a style code are present** — a barcode on every size at all three
  (150, 150 and 30 products); a maker's style code at eapavi and About You, never at Zalando.
- **Zalando's sustainable rate** — the HTML met 429 after ~50 requests at one every 2 s; the
  GraphQL path was not run long enough to know. The HTML paging limit (`?p=900` refused) does
  not apply to GraphQL.
- **How much of eapavi's women's, men's and children's sections is shoes** — all of it; see
  *eapavi in full*.

Next: a sample of 200–300 product pages from each shop, measured for those three numbers,
and the reading rules written against what it shows — as every category so far.
