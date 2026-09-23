"""mdata.lv phones, off the shop's own pages.

Written against 332 real products collected on 22.09.2026. The address of a category is the
same shape as rdveikals' — `categories/lv/475/sort/5/filter/0_0_0_0/page/N/…` — and the
engine underneath is the same, but the template is a later one and not a single selector
carries over. Read it as its own shop.

## What the listing gives and what the page adds

A card carries the id, the maker, the price with the price before a discount, a badge that
says how soon the thing ships, and an address whose slug spells the whole name. It does not
carry a barcode, and the barcode is why the product page is opened: 8 listing pages and
then one request per phone, about a hundred in all.

The product page answers in `schema.org` JSON, and the shop has put two of its fields the
wrong way round. `model` holds the **barcode** and `mpn` holds an internal number; the
maker's actual part number is in the prose of `description`, behind `Manufacturer code:`.
Nothing here trusts a field by its name.

That description is the shop's own specification, one fact to a line: `Model iPhone 15`,
`Built-in Memory 128 GB`, `RAM 6GB`, `Black`. Two spellings for the capacity — `Built-in
Memory` and `Built-in storage` — and on the records the shop has not described, the whole
of it is `EAN: … | Manufacturer code: … | Warranty: 24 m.` and nothing else.

## Stock is a class, not a word

Every card carries the same five labels — `VEIKALĀ`, `Jaunums`, `1-2 days`, `3-5 days` and
a discount — because they are the legend rather than the answer. Which one applies is the
badge's **class**: `v` 14, `vv` 90, `vvv` 235 across the 339. All three mean the thing can
be bought, so this shop says how soon rather than whether, and there is no out-of-stock
state to read. If one ever appears it will read as unknown, which is the right way round.

## Second-hand is 71% of this shop and it is dropped

237 of the 332 are `Demo` or `Renew`: mdata sells refurbished as its main trade, and the
front page says so. Dropping them is what every other channel here does, and it is a patch
over a gap rather than a policy — `offers.condition` exists, the whole pipe to it is laid,
and nothing writes anything but `new`. Written down in TODO.md with what has to be settled
before it changes. What is left is about 95 phones, all of them with a real barcode.
"""

import asyncio
import html
import json
import re
from typing import Any

import lxml.html

from app.features.runs.channel import Listing, Part, Snapshot, register
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import Job

SLUG = "mdata-phones"
SITE = "https://mdata.lv"
# The category id is part of what this channel knows: 475 is `Mobilie telefoni`.
CATEGORY = 475
LISTING = f"{SITE}/categories/lv/{{category}}/sort/5/filter/0_0_0_0/page/{{page}}/{{slug}}.html"
CATEGORY_SLUG = "Mobilie-telefoni"
# The tablets' own category, `Planšetdatori`.
TABLETS_SLUG = "mdata-tablets"
TABLET_CATEGORY = 556
TABLET_CATEGORY_SLUG = "Planšetdatori"
# 8 pages held 332 products at 48 a page when this was written.
MAX_PAGES = 60

_PAGE_LINK = re.compile(r"/page/(\d+)/")
_PRODUCT = re.compile(r"products/lv/\d+/(\d+)/")
# Second-hand, in the words this shop and the others use for it.
SECOND_HAND = re.compile(
    r"(?i)\b(demo|renew|renewd|refurb\w*|pre-owned|used|lietot\w*|mazlietot\w*|atjaunot\w*"
    r"|grade\s?[abc]|b-stock)\b"
)
# The badge's class picks which of its five fixed labels applies. All three stock classes
# mean it can be bought; the shop says how soon rather than whether.
SHIPS_IN = {"v": "VEIKALĀ", "vv": "1-2 days", "vvv": "3-5 days"}


class MData:
    """One channel: this shop's phones, off its pages."""

    def __init__(
        self, slug: str = SLUG, category: int = CATEGORY, category_slug: str = CATEGORY_SLUG
    ) -> None:
        self.slug = slug
        self.category = category
        self.category_slug = category_slug

    async def discover(self, fetcher: Fetcher, job: Job) -> list[Listing]:
        first = await self._page(fetcher, 1)
        # Whether the page holds products at all, not whether any survived the filter. On
        # 23.09.2026 all 48 cards on the first page were demo and second-hand stock, the
        # filter rightly dropped every one, and the run failed as if the category were gone
        # — with seven more pages of new phones behind it.
        if not _has_products(first.body, self.category):
            raise ValueError(f"no products on the first page of category {self.category}")

        last = min(_last_page(first.body), MAX_PAGES)
        rest = await asyncio.gather(*(self._page(fetcher, page) for page in range(2, last + 1)))

        seen: dict[str, Listing] = {}
        for part in (first, *rest):
            for card in _cards(part.body, self.category):
                seen.setdefault(card.external_id, card)
        return list(seen.values())

    async def fetch(self, fetcher: Fetcher, listing: Listing) -> Snapshot:
        """The page, for the barcode. The card has everything else."""
        detail = await fetcher.get(listing.url, role="detail")
        return Snapshot(
            external_id=listing.external_id,
            parts=[
                detail,
                Part(
                    role="card",
                    url=listing.url,
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
        # Also here and not only in `discover`: a reparse reads the snapshots on disk and
        # never asks the listing again, so a filter that lived only up there would let a
        # refurbished phone back in the first time the reader improved.
        if SECOND_HAND.search(str(fields.get("name") or "")):
            raise ValueError(f"{snapshot.external_id} is a second-hand phone")
        return fields

    def read_listing(self, listing: Listing) -> dict[str, Any]:
        return dict(listing.card)

    async def _page(self, fetcher: Fetcher, page: int) -> Part:
        return await fetcher.get(
            LISTING.format(category=self.category, page=page, slug=self.category_slug),
            role="listing",
            headers={"Accept-Language": "lv"},
        )


def _last_page(body: str) -> int:
    """The highest page the paginator names, which is the end of the category."""
    return max((int(n) for n in _PAGE_LINK.findall(body)), default=1)


def _has_products(body: str, category: int = CATEGORY) -> bool:
    """Whether a listing page carries any product card, whatever it is."""
    doc = lxml.html.fromstring(body)
    return bool(doc.cssselect(f'div.product_box_listing a[href*="products/lv/{category}/"]'))


def _cards(body: str, category: int = CATEGORY) -> list[Listing]:
    """What each card says, in the shop's own words and with nothing decided."""
    doc = lxml.html.fromstring(body)
    cards: list[Listing] = []
    for box in doc.cssselect("div.product_box_listing"):
        link = _one(box, f'a[href*="products/lv/{category}/"]')
        if link is None:
            continue
        href = link.get("href") or ""
        found = _PRODUCT.search(href)
        image = _one(box, "img[alt]")
        name = html.unescape((image.get("alt") or "").strip()) if image is not None else ""
        if found is None or not name or SECOND_HAND.search(name):
            continue

        cards.append(
            Listing(
                external_id=found.group(1),
                url=f"{SITE}/{href.lstrip('/')}",
                card={
                    "id": found.group(1),
                    "name": name,
                    "brand": _text(_one(box, ".product_companies_name")),
                    "prices": _prices(box),
                    "currency": "EUR",
                    "availability": _ships_in(box),
                },
            )
        )
    return cards


def _prices(box: Any) -> list[str]:
    """Every price on the card, in the order the shop printed them.

    A card on sale prints the price before the discount first and the one you pay second, so
    the last is the one that is charged. Both go over: which of two numbers a shop means is
    not a channel's decision, and the pair is the evidence for it.
    """
    block = _one(box, ".product_price")
    if block is None:
        return []
    return re.findall(r"\d[\d\s]*[.,]\d{2}", _text(block).replace(" ", " "))


def _ships_in(box: Any) -> str:
    """How soon, as the shop's own label — never whether, which it does not say."""
    for badge in box.cssselect(".badge"):
        for name in (badge.get("class") or "").split():
            if name in SHIPS_IN:
                return (badge.get(f"data-type-{name}") or SHIPS_IN[name]).strip()
    return ""


def _from_page(body: str, *, card: dict[str, Any]) -> dict[str, Any]:
    """The page's own record, joined to what the card already knew."""
    product = _product_json(body)
    description = str(product.get("description") or "")
    specs = _specs(description)
    offers = product.get("offers") or {}

    fields = dict(card)
    fields["name"] = product.get("name") or card.get("name") or ""
    fields["brand"] = card.get("brand") or offers.get("brand") or ""
    fields["specs"] = specs
    # The shop's `model` holds the barcode and its `mpn` an internal number, so both go
    # over as candidates and `normalization/barcodes.py` decides, as it does for every shop.
    fields["barcodes"] = _codes(product, specs)
    fields["mpn"] = specs.get("Manufacturer code", "")
    if offers.get("price"):
        fields["price"] = str(offers["price"])
    prices = card.get("prices") or []
    if prices:
        # The card prints the price before a discount first, so the last is what is charged.
        fields["price"] = prices[-1].replace(" ", "").replace(" ", "")
    return fields


def _product_json(body: str) -> dict[str, Any]:
    """The `schema.org` Product block, of the two the page carries."""
    for found in re.finditer(
        r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", body, re.DOTALL
    ):
        try:
            data = json.loads(found.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "Product":
            return data
    return {}


def _specs(description: str) -> dict[str, str]:
    """The shop's specification, one fact to a line.

    Two shapes, both real: `Model iPhone 15` with the name of the fact in front, and
    `EAN: 195949036064` with a colon. A line that is neither — a bare `Black`, a bare `5G` —
    is kept under its own text, because a colour arrives that way and dropping it would
    throw away the one axis this shop states plainly.
    """
    specs: dict[str, str] = {}
    for line in re.split(r"[\n|]", description):
        line = " ".join(line.split())
        if not line:
            continue
        labelled = re.match(r"([A-Za-z][A-Za-z\- ]{2,30}):\s*(.+)$", line)
        if labelled:
            specs.setdefault(labelled.group(1).strip(), labelled.group(2).strip())
            continue
        # `Colour` and `Storage` were missing, so `Colour Black/Green` was kept whole as its own
        # name and value, and no lookup of a field name could find the colour in it.
        known = re.match(
            r"(Model|Built-in Memory|Built-in storage|Storage|Colour|RAM|OS|Screen)\s+(.+)$", line
        )
        if known:
            specs.setdefault(known.group(1), known.group(2).strip())
            continue
        specs.setdefault(line, line)
    return specs


def _codes(product: dict[str, Any], specs: dict[str, str]) -> list[str]:
    """Every number that could be a barcode, from wherever the shop put it."""
    found: list[str] = []
    for value in (product.get("model"), product.get("mpn"), specs.get("EAN")):
        digits = re.sub(r"\D", "", str(value or ""))
        if digits and digits not in found:
            found.append(digits)
    return found


def _one(element: Any, selector: str) -> Any:
    found = element.cssselect(selector)
    return found[0] if found else None


def _text(element: Any) -> str:
    if element is None:
        return ""
    return html.unescape(" ".join(element.text_content().split())).strip()


register(MData())
TABLETS_CHANNEL = register(
    MData(slug=TABLETS_SLUG, category=TABLET_CATEGORY, category_slug=TABLET_CATEGORY_SLUG)
)
