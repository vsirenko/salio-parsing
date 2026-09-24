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

## Open, and the next step

- **How often the price differs by size** — not measured; the three pages above all had one
  price.
- **How often a barcode and a style code are present** across a whole shop, not three pages.
- **How much of eapavi's women's, men's and children's sections is shoes** — they include
  bags and accessories.

Next: a sample of 200–300 product pages from each shop, measured for those three numbers,
and the reading rules written against what it shows — as every category so far.
