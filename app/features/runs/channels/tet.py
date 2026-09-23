"""tet.lv phones, read off the shop's own pages.

**The listing already holds most of it.** Every card carries the shop's id, the name, the
brand, the category, the price and — unusually — the manufacturer's code, on 333 of 333.
Six requests of sixty therefore bring back the whole category's prices, stock and part
numbers without a product page being opened, which is what `delivers_quick` is for. The
product page adds one thing and it is the valuable one: `#i-product-data` states the
barcode, on 40 of 40 sampled.

**Page seven is not empty and not a repeat of page six.** It answers with sixty products,
every one of them already seen — the listing wraps round rather than ending. A walk that
stopped when a page matched the one before it would never stop at all, so this one stops
when a page brings nothing new.

**The page's own JSON-LD says `InStock` for everything**, including the three of forty
sampled that the shop itself flags `Drīzumā` — coming soon. That is the fourth shop here in
a row whose structured data means the shop will sell the thing rather than that it has it,
after dateks, bm.market and euronics. The flag is what travels.

**Refurbished phones sit in the same category and are deliberately left out.** Fourteen say
so in English — `Apple iPhone 12 64GB Black Pre-owned C grade [Refurbished]`, brand
`APPLE RENEWD` — and three more say so in Latvian, `[Mazlietots]`, which this channel missed
at first and which is how a used `Galaxy S24+` at 799 euro came to stand as the cheapest
price for a new one. Their part numbers are the refurbisher's own, so nothing would confuse
them by code. By brand and model it would: that iPhone 12 costs 198 euro and would attach to
the entry for a new one and show as its cheapest price. Nothing in this system distinguishes
condition yet, which is the same reason cec's refurbished section is not collected either.

Because the price and the stock flag are on the listing and the barcode is on the product
page, **the card is written into the snapshot beside the page**, as euronics and bigbox both
do: a snapshot that needed a second document to be readable would not be a snapshot.
"""

import json
from typing import Any

import lxml.html

from app.features.runs.channel import Listing, Part, Snapshot, register
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import Job

SLUG = "tet-phones"
SITE = "https://www.tet.lv"
CATEGORY_PATH = "/veikals/telefoni/telefoni-un-aksesuari/viedtalruni.html"
# The tablets' own leaf; e-readers and covers are leaves beside it.
TABLETS_SLUG = "tet-tablets"
TABLET_CATEGORY_PATH = "/veikals/datortehnika/plansetdatori-un-aksesuari/plansetdatori.html"
# Sixty to a page, six pages of them when this was written. The bound is against a listing
# that stopped paging rather than against a shop that grew.
MAX_PAGES = 40
# What the shop calls the condition it does not sell as new — in both its languages. The
# Latvian one was missing when this was written and three used phones went through: a
# `Galaxy S24+ 512GB` at 799 euro attached to the entry for a new one and stood there as its
# cheapest price. See the module docstring on why they are left out at all.
REFURBISHED = ("RENEWD", "REFURBISHED", "PRE-OWNED", "MAZLIETOT")
# The shop's flag for a product it has not got yet. Its absence is the availability: 325 of
# 333 carry nothing at all.
SOON = "Drīzumā"


class Tet:
    """One channel: this shop's phones, off its pages."""

    def __init__(self, slug: str = SLUG, category_path: str = CATEGORY_PATH) -> None:
        self.slug = slug
        self.category_path = category_path

    async def discover(self, fetcher: Fetcher, job: Job) -> list[Listing]:
        """Walk until a page brings nothing new, which is not the same as until it repeats.

        The cheap pass stops here with everything it needs: the price, the stock flag and
        the part number are all on the card.
        """
        seen: dict[str, Listing] = {}
        for page in range(1, MAX_PAGES + 1):
            part = await self._page(fetcher, page)
            cards = _cards(part.body)
            if not cards:
                break
            fresh = [card for card in cards if card.external_id not in seen]
            if not fresh:
                # The listing wrapped round to the start rather than ending.
                break
            for card in fresh:
                seen[card.external_id] = card

        if not seen:
            raise ValueError(f"no products on {self.category_path}")
        return list(seen.values())

    async def fetch(self, fetcher: Fetcher, listing: Listing) -> Snapshot:
        """The product page for the barcode, and the card for everything else."""
        page = await fetcher.get(SITE + listing.url, role="detail")
        return Snapshot(
            external_id=listing.external_id,
            parts=[
                page,
                Part(
                    role="card",
                    url=SITE + self.category_path,
                    status=200,
                    body=json.dumps(listing.card, ensure_ascii=False),
                ),
            ],
        )

    def parse(self, snapshot: Snapshot) -> dict[str, Any]:
        page = snapshot.part("detail")
        if page is None:
            raise ValueError("snapshot has no product page")
        card = snapshot.part("card")
        fields = _from_page(page.body, card=json.loads(card.body) if card else {})
        # Also here, not only in `discover`: a reparse reads the snapshots on disk and never
        # asks the listing again, so a filter that lived only up there let three used phones
        # back in the first time the reader improved.
        if _is_refurbished(str(fields.get("name") or ""), str(fields.get("brand") or "")):
            raise ValueError(f"{snapshot.external_id} is a second-hand phone")
        return fields

    def read_listing(self, listing: Listing) -> dict[str, Any]:
        return dict(listing.card)

    async def _page(self, fetcher: Fetcher, page: int) -> Part:
        suffix = "" if page == 1 else f"?page={page}"
        return await fetcher.get(
            f"{SITE}{self.category_path}{suffix}",
            role="listing",
            headers={"Accept-Language": "lv"},
        )


def _cards(html: str) -> list[Listing]:
    """The listing's own record of each product, off the analytics attributes on the card.

    A refurbished phone is dropped here rather than read and filtered later: the channel is
    where a shop's own categories are turned into what a pass collected, and a used phone in
    a catalogue that cannot tell conditions apart is a wrong price rather than a missing one.
    """
    doc = lxml.html.fromstring(html)
    cards: list[Listing] = []
    for item in doc.cssselect(".i-product-item[data-id]"):
        external_id = (item.get("data-id") or "").strip()
        link = _one(item, "a.i-product-item__link[href]")
        if not external_id or link is None:
            continue

        name = (item.get("data-name") or "").strip()
        brand = (item.get("data-brand") or "").strip()
        if _is_refurbished(name, brand):
            continue

        cards.append(
            Listing(
                external_id=external_id,
                url=link.get("href") or "",
                card={
                    "id": external_id,
                    "url": link.get("href") or "",
                    "name": name,
                    "brand": brand,
                    "category": (item.get("data-category") or "").strip(),
                    "price": (item.get("data-price") or "").strip(),
                    "currency": "EUR",
                    # The maker's code, which this shop puts on the card and most do not.
                    "mpn": (item.get("data-mpn") or "").strip(),
                    # The shop's own word, and its absence is the answer.
                    "availability": SOON if _says_soon(item) else "",
                },
            )
        )
    return cards


def _is_refurbished(name: str, brand: str) -> bool:
    haystack = f"{name} {brand}".upper()
    return any(word in haystack for word in REFURBISHED)


def _says_soon(item: Any) -> bool:
    return any(
        SOON in " ".join(flag.text_content().split())
        for flag in item.cssselect(".i-product-item__flag-item-title")
    )


def _from_page(html: str, *, card: dict[str, Any]) -> dict[str, Any]:
    """The shop's own fields, from the page and the card together.

    The page's JSON-LD is deliberately not read for availability: it says `InStock` for
    every product, including the ones the shop itself flags as not yet in.
    """
    doc = lxml.html.fromstring(html)
    data = _one(doc, "#i-product-data")
    attributes = dict(data.attrib) if data is not None else {}

    return {
        "id": card.get("id") or "",
        "url": card.get("url") or "",
        "name": card.get("name") or "",
        "brand": attributes.get("data-product-brand") or card.get("brand") or "",
        "category": card.get("category") or "",
        # Only the page has it, and it has it on every product sampled.
        "ean": (attributes.get("data-product-ean") or "").strip(),
        "mpn": (attributes.get("data-product-mpn") or card.get("mpn") or "").strip(),
        "price": card.get("price") or "",
        "currency": card.get("currency") or "EUR",
        "availability": card.get("availability") or "",
        "specs": _specs(doc),
        "images": _images(doc),
    }


def _specs(doc: Any) -> dict[str, str]:
    """The `Datu lapa` table as the shop writes it, name to value.

    The label carries a help bubble beside it, which reads as part of the name if the cell
    is taken whole — so the label's own text element is what is read.
    """
    specs: dict[str, str] = {}
    for row in doc.cssselect(".i-specs-table__row"):
        name = _text(_one(row, ".i-specs-table__label-text")) or _text(
            _one(row, ".i-specs-table__label")
        )
        value = _text(_one(row, ".i-specs-table__value"))
        name = name.rstrip(":")
        if name and value:
            specs.setdefault(name, value)
    return specs


def _images(doc: Any) -> list[str]:
    seen: list[str] = []
    for image in doc.cssselect("img.i-product-page__gallery-image[src]"):
        source = (image.get("src") or "").strip()
        if source and source not in seen:
            seen.append(source)
    return seen


def _one(doc: Any, css: str) -> Any:
    found = doc.cssselect(css)
    return found[0] if found else None


def _text(element: Any) -> str:
    return "" if element is None else " ".join(element.text_content().split())


register(Tet())
TABLETS_CHANNEL = register(Tet(slug=TABLETS_SLUG, category_path=TABLET_CATEGORY_PATH))
