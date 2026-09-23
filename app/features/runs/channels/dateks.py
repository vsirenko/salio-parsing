"""dateks.lv phones, read off the shop's own pages.

**The category moved, and the old address still answers 200.** The previous parser of this
shop walked `/cenas/mobilie-telefoni`; that slug is now a section landing page which serves
a full 42 KB of navigation, a matching `<h1>`, and not one product. No redirect, no 404 —
the shop looks open and empty. The phones are at `/cenas/viedtalruni`. This is why
`discover` refuses a first page with no cards on it rather than returning an empty list: a
channel that reports nothing is indistinguishable from a shop that sold nothing, and the
absence it would licence is exactly what the run contract exists to prevent.

**The page number in the address is one less than the page.** `/cenas/viedtalruni` and
`/cenas/viedtalruni/pg/0` are both page 1, `/pg/1` is page 2, and the paginator shows it:
on `/pg/1` the element marked current reads `2`. Walking `pg/1 … pg/31` therefore collects
pages 2 to 32 and silently drops the first 24 products of 745. The count comes from the
paginator, which lists every page rather than a window — 33 labels for 32 pages when this
was written — so the rest are asked for together rather than walked.

**The listing carries what a cheap pass needs, and the analytics block does not.** Measured
over all 745 phones: the name, the price with VAT, the price without it, the manufacturer
code and a stock line are on 100% of cards. The GA4 `var impressions` array beside them has
the brand but no manufacturer code, and it is not dependable — it appeared on 73.2% of the
pages of one walk and on none of them an hour later. So everything here is read from the
markup, and the brand, which the listing has no room for, comes off the product page.

**`availability` in the page's own schema.org block is wrong.** It reads `InStock` on every
product. The shop's own words disagree: of 745 phones, 208 say `Noliktavā` and 513 say
`Pasūtāms`, so 71.2% of what the markup calls in stock is in fact to order. The words are
returned and the schema.org claim is not.

**A card states its barcode more than once.** `div.specs` holds two blocks, `translated`
(Latvian) and `original` (English), and a code appears in both under whichever of `EAN`,
`Eans` and `GTIN` the supplier used — six lines for one number is ordinary. Sometimes the
numbers genuinely differ: a UPC-A beside the same GTIN zero-padded to 13, two adjacent
codes for sibling variants, and on one Apple card two unrelated ones. Which of them is a
barcode is not this channel's decision — the whole list goes over and
`normalization/barcodes.py` picks, as it does for every shop.
"""

import asyncio
import json
import re
from typing import Any

import lxml.html

from app.features.runs.channel import Listing, Part, Snapshot, register
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import Job

SLUG = "dateks-phones"
SITE = "https://www.dateks.lv"
# The shop's word for smartphones. `mobilie-telefoni` is the section above it and holds no
# products — see the module docstring; a different category is a different channel.
CATEGORY_SLUG = "viedtalruni"
# The same pages under the shop's word for tablets.
TABLETS_SLUG = "dateks-tablets"
TABLET_CATEGORY_SLUG = "plansetdatori"
# Zero-based: page N is `/pg/N-1`, and page 1 is `/pg/0`.
LISTING = f"{SITE}/cenas/{{slug}}/pg/{{page}}"
# A category that suddenly claims hundreds of pages is a site that changed, not a shop that
# grew overnight. 32 pages held 745 phones when this was written.
MAX_PAGES = 200

_PAGE_LINK = re.compile(r"/cenas/[a-z0-9-]+/pg/(\d+)")
_PRODUCT_URL = re.compile(r"/cenas/[a-z0-9-]+/(\d+)-")
# `Preces kods: 5109CJCV`, `ID: 1404114` — the label the shop prints in front of each.
_LABELLED = re.compile(r"^[^:]*:\s*")
# `Noliktavā 3 gab.` — the word the shop uses for the state, and the count beside it.
_STOCK = re.compile(r"\b(Noliktavā|Pasūtāms|Birojā|Nav pieejams)\b(?:\s*(\d+)\s*gab)?")
# What the shop calls a barcode, in either specification block.
_BARCODE = re.compile(r"^(?:Eans?|EAN|GTIN)$", re.IGNORECASE)


class Dateks:
    """One channel: this shop's phones, off its pages."""

    def __init__(self, slug: str = SLUG, category_slug: str = CATEGORY_SLUG) -> None:
        self.slug = slug
        self.category_slug = category_slug

    async def discover(self, fetcher: Fetcher, job: Job) -> list[Listing]:
        """Both kinds walk the listing, and the cheap pass stops there.

        The first page says how many there are and the rest are asked for together, which
        is the entire cost of the cheap pass: 32 requests for the prices and stock of the
        whole category, with no product page opened.
        """
        first = await self._page(fetcher, 0)
        cards = _cards(first.body)
        if not cards:
            # Not an empty shop. The address stopped being a category — which is how this
            # shop announces a move, with a 200 and a page full of navigation.
            raise ValueError(f"no products on the first page of /cenas/{self.category_slug}")

        last = min(_last_page(first.body), MAX_PAGES)
        rest = await asyncio.gather(*(self._page(fetcher, page) for page in range(1, last + 1)))

        seen: dict[str, Listing] = {}
        for card in cards:
            seen.setdefault(card.external_id, card)
        for part in rest:
            for card in _cards(part.body):
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
            LISTING.format(slug=self.category_slug, page=page),
            role="listing",
            headers={"Accept-Language": "lv"},
        )


def _last_page(html: str) -> int:
    """The highest page index the paginator names, which is the last one.

    Every page is listed rather than a window around the current one, so this is the whole
    category and not the next few pages of it.
    """
    return max((int(n) for n in _PAGE_LINK.findall(html)), default=0)


def _cards(html: str) -> list[Listing]:
    """The listing's own record of each product.

    Everything a cheap pass needs is printed on the card, so this opens nothing and decides
    nothing: the stock word is kept as the shop wrote it, because what `Pasūtāms` is worth
    is a reading decision and this is not the place for it.
    """
    doc = lxml.html.fromstring(html)
    cards: list[Listing] = []
    for prod in doc.cssselect("div.prod"):
        link = _one(prod, "a.imp[href]")
        if link is None:
            continue
        external_id = (link.get("data-id") or "").strip()
        url = _absolute(link.get("href") or "")
        if not external_id or not url:
            continue
        state, quantity = _stock(_text(_one(prod, ".avail")))
        cards.append(
            Listing(
                external_id=external_id,
                url=url,
                card={
                    "id": external_id,
                    "url": url,
                    "name": _text(_one(prod, ".name")),
                    # `Preces kods` is the maker's, not the shop's counter — the page's own
                    # schema.org block calls the same string `mpn`. The shop's number is
                    # `id`, and it is deliberately not offered under a name the generic
                    # reader takes for a part number.
                    "mpn": _labelled(_one(prod, ".code")),
                    "price": _amount(_text(_one(prod, ".price"))),
                    "price_ex_vat": _amount(_text(_one(prod, ".price_sec"))),
                    "currency": "EUR",
                    "availability": state,
                    "quantity": quantity,
                    # `Saņem Dateks birojā rīt, 23.09` — when, in the shop's own words. It
                    # sits in the spans above the stock line rather than in a class of its
                    # own, and is the whole of what the card says about delivery.
                    "delivery": " ".join(
                        _text(span) for span in prod.cssselect(".avail span") if _text(span)
                    ),
                },
            )
        )
    return cards


def _from_page(html: str, *, url: str) -> dict[str, Any]:
    """The shop's own fields, from the two things the page carries.

    The schema.org block is taken for the names, the brand and the price — its price is the
    one with VAT, the same number the listing prints — and its `availability` is dropped on
    purpose, because it reads `InStock` whatever the shop actually has.
    """
    doc = lxml.html.fromstring(html)
    product = _schema_product(doc)
    offers = product.get("offers") or {}
    brand = product.get("brand") or {}
    specs = _specs(doc, "translated")
    original = _specs(doc, "original")
    state, quantity = _stock(_availability_text(doc))

    return {
        "id": str(product.get("sku") or "") or _id_from(url),
        "url": url,
        "title": _text(_one(doc, "h1")),
        "name": product.get("name") or "",
        "brand": (brand.get("name") if isinstance(brand, dict) else str(brand)) or "",
        "mpn": product.get("mpn") or _labelled(_one(doc, ".code")),
        "price": offers.get("price"),
        "currency": offers.get("priceCurrency") or "EUR",
        # `https://schema.org/NewCondition` -> `NewCondition`. The generic reader lowercases
        # what it finds, and an outlet or refurbished phone is listed here as its own state.
        "condition": str(offers.get("itemCondition") or "").rsplit("/", 1)[-1].strip(),
        # The shop's word, never the schema.org claim beside it.
        "availability": state,
        "quantity": quantity,
        # Every code the page states, under whichever label, from both blocks and
        # de-duplicated. Choosing among them is `normalization/barcodes.py`'s job.
        "barcodes": _barcodes(specs, original),
        "specs": specs,
        # The same table before the shop translated it, whose names are English. Carried
        # because it is what a language-neutral attribute registry would key on, while the
        # category rules still read the Latvian one.
        "specs_original": original,
        # The shop's own table, `Visi parametri`: the same names on every product whoever
        # supplied it, where the two blocks above are each supplier's own and differ card to
        # card — nine names for a tablet's diagonal among them, and on 127 of 402 tablets no
        # diagonal at all, while this one stated it on every page looked at.
        "parameters": _parameters(doc),
        "images": _images(doc),
    }


def _schema_product(doc: Any) -> dict[str, Any]:
    """The JSON-LD `Product`, or nothing if the page stopped carrying one.

    Nothing here is required: the listing already gave the id, the name, the price and the
    manufacturer code, so a page without the block parses into a product missing its brand
    rather than into a failure.
    """
    for blob in doc.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            data = json.loads(blob)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "Product":
            return data
    return {}


def _parameters(doc: Any) -> dict[str, str]:
    """The shop's own parameter table, as name -> value.

    Groups of `span.k` / `span.v` pairs under `#params`. Each name can carry a help text in
    `div.descr` beside it, which is prose about the parameter and not its value, so only the
    two spans are read.
    """
    table = _one(doc, "#params")
    if table is None:
        return {}
    found: dict[str, str] = {}
    for row in table.cssselect("div.fv"):
        name, value = row.cssselect("span.k"), row.cssselect("span.v")
        if not name or not value:
            continue
        key, text = _text(name[0]), _text(value[0])
        if key and text:
            found.setdefault(key, text)
    return found


def _specs(doc: Any, which: str) -> dict[str, str]:
    """One of the two specification blocks, as name -> value.

    The block is a run of `Name - Value` lines separated by `<br>` rather than a table, and
    the name often carries its group — `Displejs - Displeja diagonāle - 16,8 cm (6,6")`.
    Splitting at the last separator keeps the whole name together and leaves the value
    intact; splitting at the first would file the diagonal under `Displejs` and let the next
    display row overwrite it.
    """
    block = _one(doc, f"div.specs div.{which}")
    if block is None:
        return {}

    specs: dict[str, str] = {}
    for line in _lines(block):
        name, separator, value = line.rpartition(" - ")
        if not separator or not name:
            continue
        specs.setdefault(name, value)
    return specs


def _lines(block: Any) -> list[str]:
    """The block's text, cut at every `<br>`, in one walk of the tree.

    Serialising the block and re-parsing each piece reads better and costs two and a half
    thousand parser invocations per phone: this table runs to 270 rows and the page carries
    it twice. Text arrives as an element's `text` and each child's `tail`, so one pass over
    the children collects the same lines with no parsing at all.
    """
    lines: list[str] = []
    current: list[str] = [block.text or ""]
    for child in block.iter():
        if child is block:
            continue
        if child.tag == "br":
            lines.append(" ".join("".join(current).split()))
            current = []
        else:
            current.append(child.text or "")
        current.append(child.tail or "")
    lines.append(" ".join("".join(current).split()))
    return [line for line in lines if line]


def _barcodes(*blocks: dict[str, str]) -> list[str]:
    found: list[str] = []
    for specs in blocks:
        for name, value in specs.items():
            code = str(value).strip()
            if _BARCODE.match(name.strip()) and code.isdigit() and code not in found:
                found.append(code)
    return found


def _availability_text(doc: Any) -> str:
    """The stock line, which is not the only element on the page wearing that class.

    A script block and the sticky bar at the foot of the page both carry it, and the bar
    holds the whole product in one string. The one that is the stock line is the one whose
    text is a stock word.
    """
    for element in doc.cssselect(".avail"):
        text = _text(element)
        if _STOCK.search(text):
            return text
    return ""


def _stock(text: str) -> tuple[str, int | None]:
    found = _STOCK.search(text or "")
    if found is None:
        return "", None
    return found.group(1), int(found.group(2)) if found.group(2) else None


def _images(doc: Any) -> list[str]:
    seen: list[str] = []
    for image in doc.cssselect("div.gal img[src], div.pics img[src]"):
        url = _absolute(image.get("src") or "")
        if url and url not in seen:
            seen.append(url)
    return seen


def _one(doc: Any, css: str) -> Any:
    found = doc.cssselect(css)
    return found[0] if found else None


def _text(element: Any) -> str:
    return "" if element is None else " ".join(element.text_content().split())


def _labelled(element: Any) -> str:
    """`Preces kods: 5109CJCV` -> `5109CJCV`."""
    return _LABELLED.sub("", _text(element)).strip()


def _amount(text: str) -> str:
    """`323,81 €` and `267,61 € bez PVN` -> `323.81`, `267.61`.

    A comma is the decimal separator here. Left as a string: turning it into a number is
    the reader's job, and it already knows how.
    """
    found = re.search(r"\d[\d\s]*(?:[.,]\d+)?", text or "")
    if not found:
        return ""
    return found.group(0).replace(" ", "").replace("\xa0", "").replace(",", ".")


def _absolute(href: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return SITE + ("" if href.startswith("/") else "/") + href


def _id_from(url: str) -> str:
    found = _PRODUCT_URL.search(url)
    return found.group(1) if found else ""


CHANNEL = register(Dateks())
TABLETS_CHANNEL = register(Dateks(slug=TABLETS_SLUG, category_slug=TABLET_CATEGORY_SLUG))
