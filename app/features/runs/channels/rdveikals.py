"""rdveikals.lv (RD Electronics) phones, read off the shop's own pages.

The first channel here that has to read markup, and the first with a cheap pass.

**Discovery is the listing, and the sitemap is a trap.** `sitemap.xml` looks like the
better door — one request, 4.7 MB gzipped, the whole shop — and it is not. Walked on the
same afternoon, the listing held 1400 phones and the sitemap 1382, and neither contained
the other: 39 products were on sale and absent from the sitemap, 21 were in the sitemap and
gone from the shop. Every one of the sitemap-only products sampled answered 404. It is
generated on its own schedule, so it is late on what arrived and wrong about what left —
and both halves of that are damaging here. A new phone invisible until the file regenerates
is a new phone nobody can compare, and a dead one kept alive by a pass that "saw" it is
exactly the absence inference the run contract exists to protect.

**The listing is walked by price, never by popularity.** The shop's default sort drifts:
products move between pages while the walk is in progress, and the same walk repeated yields
about three quarters of the category, differently each time. `sort/6` is by price and holds
still. 78 pages, 18 cards each.

**The cheap pass is that same listing**, because the card carries what a cheap pass is for:
`data-prod-price` and `data-prod-available` on every `li`, 18 products per 62 KB gzipped.
That is the whole shop's prices in 78 requests with no product page opened — what
`delivers_quick` was declared for and what no channel here could do until now.

**The brand comes out of the analytics block, not the markup.** The page carries a GA4
`view_item` push whose object names the brand, the product and the category separately and
cleanly. The microdata beside it does not: `h1 [itemprop=brand]` reads `mobilais telefons
Panasonic`, with the word for the category inside the element naming the maker. Reading the
JSON costs one regular expression and avoids teaching this channel any Latvian at all.

What the analytics block does not have is the barcode or the specification table, so all
three things the page carries are read: the JSON for the names, the microdata for the
barcode, and `#product_char` for the specifications.
"""

import asyncio
import json
import re
from typing import Any

import lxml.html

from app.features.runs.channel import Listing, Part, Snapshot, register
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import Job

SLUG = "rdveikals-phones"
SITE = "https://www.rdveikals.lv"
# The shop's own id for this category, and the words it puts in the URL. Both are part of
# what this channel knows: a different category is a different channel.
CATEGORY_ID = 388
CATEGORY_SLUG = "Mobilie-telefoni"
# sort 6 is by price. The default, 5, is by popularity, and under it products move between
# pages while the walk is in progress — the listing then yields about three quarters of the
# category however many times it is walked.
LISTING = f"{SITE}/categories/lv/{{category}}/sort/6/filter/0_0_0_0/page/{{page}}/{{slug}}.html"
# A category that suddenly claims hundreds of pages is a site that changed, not a shop that
# grew overnight. 78 pages held 1400 phones when this was written.
MAX_PAGES = 200

_PRODUCT_URL = re.compile(r"/products/lv/(\d+)/(\d+)/")
_PAGE_LINK = re.compile(r"/page/(\d+)/")
# The GA4 push. Anchored on the event name because the page pushes several objects and only
# this one describes the product.
_VIEW_ITEM = re.compile(r'dataLayer\.push\((\{"event":"view_item".*?\})\);', re.DOTALL)


class Rdveikals:
    """One channel: this shop's phones, off its pages."""

    slug = SLUG

    async def discover(self, fetcher: Fetcher, job: Job) -> list[Listing]:
        """Both kinds walk the listing; only what happens afterwards differs.

        There is no cheaper way in that is also correct — see the module docstring on the
        sitemap.

        The first page says how many there are, and the rest are asked for together. That
        is not a micro-optimisation on a full pass, where 78 pages sit in front of 1400
        cards: it is the entire cost of the cheap pass, which is meant to run often and has
        nothing else to do. The rate is still the fetcher's — it bounds both how many
        requests are open and how many start per second — so this waits less rather than
        asking for more.
        """
        first = await self._page(fetcher, 1)
        last = min(_last_page(first.body), MAX_PAGES)
        rest = await asyncio.gather(*(self._page(fetcher, page) for page in range(2, last + 1)))

        seen: dict[str, Listing] = {}
        for part in (first, *rest):
            for card in _cards(part.body):
                # The first page a product appears on wins. Under `sort/6` it appears on
                # exactly one, and this only guards against the shop reordering underneath.
                seen.setdefault(card.external_id, card)
        return list(seen.values())

    async def fetch(self, fetcher: Fetcher, listing: Listing) -> Snapshot:
        part = await fetcher.get(listing.url, role="detail")
        return Snapshot(external_id=listing.external_id, parts=[part])

    def parse(self, snapshot: Snapshot) -> dict[str, Any]:
        part = snapshot.part("detail")
        if part is None:
            raise ValueError("snapshot has no product page")
        return _from_page(part.body, url=snapshot.url or part.url)

    def read_listing(self, listing: Listing) -> dict[str, Any]:
        return dict(listing.card)

    async def _page(self, fetcher: Fetcher, page: int) -> Part:
        return await fetcher.get(
            LISTING.format(category=CATEGORY_ID, page=page, slug=CATEGORY_SLUG),
            role="listing",
            headers={"Accept-Language": "lv"},
        )


def _last_page(html: str) -> int:
    return max((int(n) for n in _PAGE_LINK.findall(html)), default=1)


def _cards(html: str) -> list[Listing]:
    """The listing's own record of each product, straight off the `li`.

    Everything a cheap pass needs is an attribute here, so this opens nothing and decides
    nothing — `data-prod-available` is kept as the shop wrote it (`1hour`, `9day`), because
    what those codes mean is a reading decision and this is not the place for it.
    """
    doc = lxml.html.fromstring(html)
    cards: list[Listing] = []
    for li in doc.cssselect("li.js-product[data-prod-id]"):
        external_id = li.get("data-prod-id") or ""
        link = li.cssselect("h3.product__title a[href]") or li.cssselect("a.overlay[href]")
        if not external_id or not link:
            continue
        cards.append(
            Listing(
                external_id=external_id,
                url=_absolute(link[0].get("href") or ""),
                card={
                    "id": external_id,
                    "name": (li.get("data-prod-name") or "").strip(),
                    "brand": (li.get("data-prod-brand") or "").strip(),
                    "category": (li.get("data-prod-category") or "").strip(),
                    "product_code": (li.get("data-prod-article") or "").strip(),
                    "price": li.get("data-prod-price") or None,
                    "currency": "EUR",
                    "delivery_code": (li.get("data-prod-available") or "").strip(),
                    "url": _absolute(link[0].get("href") or ""),
                },
            )
        )
    return cards


def _from_page(html: str, *, url: str) -> dict[str, Any]:
    """The shop's own fields, from all three things the page carries.

    Deliberately not our shape. In particular the article number is returned as
    `product_code` and never as `sku` or `article`: those are names the generic reader
    takes for a manufacturer's part number, and this shop's is its own six-digit counter —
    a number no other shop could ever agree with. What `itemprop=sku` holds here is the
    barcode, whatever the attribute is called.
    """
    doc = lxml.html.fromstring(html)
    item = _view_item(html)

    # Not `a or b`: an lxml element with no children is falsy, so a heading that was found
    # and happens to hold only text would be discarded in favour of the fallback.
    heading = _first_of(doc, "h1[itemprop=name]", "h1")
    offer_price = _one(doc, "[itemprop=offers] [itemprop=price]")
    currency = _one(doc, "[itemprop=offers] [itemprop=priceCurrency]")
    availability = _one(doc, "[itemprop=offers] [itemprop=availability]")
    barcode = _one(doc, "[itemprop=sku]")
    identifier = _one(doc, "[itemprop=identifier]")

    return {
        "id": item.get("item_id") or _id_from(url),
        "url": url,
        # The title as the shop shows it, and the name as its own analytics records it —
        # the second has neither the brand nor the word for the category in it.
        "title": _text(heading),
        "name": item.get("item_name") or "",
        "brand": item.get("item_brand") or "",
        "category": item.get("item_category") or "",
        "ean": (barcode.get("content") if barcode is not None else "") or "",
        "product_code": item.get("article") or _text(identifier),
        "price": item.get("price") if item.get("price") is not None else _content(offer_price),
        "currency": _content(currency) or "EUR",
        # `https://schema.org/InStock` -> `InStock`. The generic reader lowercases and maps
        # it; PreOrder is this shop's ordinary state and means "to order, N days".
        "availability": (availability.get("href") if availability is not None else "")
        .rsplit("/", 1)[-1]
        .strip(),
        "specs": _specs(doc),
        # How soon each way of getting it would arrive, in the shop's own codes.
        "delivery": {
            key: item[key]
            for key in ("delivery_store", "delivery_pickup", "delivery_courier")
            if item.get(key)
        },
        "images": _images(doc),
    }


def _view_item(html: str) -> dict[str, Any]:
    """The GA4 object describing this product, or nothing if the page stopped carrying one.

    Nothing here is required: every field it gives has a duller source in the markup, and a
    page without it parses into a product with a messier brand rather than into a failure.
    """
    found = _VIEW_ITEM.search(html)
    if found is None:
        return {}
    try:
        items = json.loads(found.group(1))["ecommerce"]["items"]
    except (ValueError, KeyError, TypeError):
        return {}
    return items[0] if items else {}


def _specs(doc: Any) -> dict[str, str]:
    """The `Datu lapa` table, as `group / name` -> value.

    The group is kept in the key because the name alone is ambiguous on this shop: it lists
    a `Krāsa` under general parameters and another under the case, and flattening them would
    let one silently overwrite the other.
    """
    root = _one(doc, "#product_char")
    if root is None:
        return {}

    specs: dict[str, str] = {}
    group = ""
    for element in root:
        if element.tag == "h3":
            group = _text(element)
            continue
        if element.tag != "dl":
            continue
        name, value = element.find(".//dt"), element.find(".//dd")
        if name is None or value is None:
            continue
        # The question marks beside a name are help bubbles, and their text reads as part
        # of the value if it is taken whole.
        for bubble in value.cssselect(".tooltip-icon, [data-plugin=tooltip]"):
            bubble.drop_tree()
        key = _text(name).rstrip(":")
        if key:
            specs[f"{group} / {key}" if group else key] = _text(value)
    return specs


def _images(doc: Any) -> list[str]:
    seen: list[str] = []
    for image in doc.cssselect("img[itemprop=image][src]"):
        url = _absolute(image.get("src") or "")
        if url and url not in seen:
            seen.append(url)
    return seen


def _one(doc: Any, css: str) -> Any:
    found = doc.cssselect(css)
    return found[0] if found else None


def _first_of(doc: Any, *selectors: str) -> Any:
    for css in selectors:
        found = _one(doc, css)
        if found is not None:
            return found
    return None


def _text(element: Any) -> str:
    return "" if element is None else " ".join(element.text_content().split())


def _content(element: Any) -> str:
    if element is None:
        return ""
    return (element.get("content") or _text(element)).strip()


def _absolute(href: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return SITE + ("" if href.startswith("/") else "/") + href


def _id_from(url: str) -> str:
    found = _PRODUCT_URL.search(url)
    return found.group(2) if found else ""


CHANNEL = register(Rdveikals())
