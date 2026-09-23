"""euronics.lv phones, read off the shop's own pages.

**Discovery is one request.** The listing pages are cumulative — page 2 holds the 30
products of page 1 and 30 more — and the `?f=` token that selects one is a protobuf
message: field 1 is the sort and field 6 is the page number. Building a token for a page
past the end therefore returns the whole category in a single response: 319 smartphones in
2 MB, with the `Load more` anchor gone. Walking them in order, as the previous parser did,
downloads the same cards over and over — the sum of 30, 60, 90 … is the square of what
there is to read.

**The product page is the richest in this project.** Its JSON-LD `@graph` states the brand,
the part number, `gtin13` **and the model** outright — 100% of a 40-product sample, every
field. No other shop here states a model at all, so this is the one channel whose ruleset
needs no rule to cut one out of a name.

Three things a reader of this shop would otherwise get wrong, each measured on all 319:

- **`data-product-brand` is `Vaikimisi` on every card** — Estonian for "default". It is a
  placeholder, not a brand, and the real one is only on the product page.
- **`data-product-price` is not always the price.** On 51 of 319 the card is labelled
  `Friends price:` and carries a `discount__old__loyal` block with the real one beside it:
  599.99 against 839.99, a 29% difference that a shopper without a loyalty card does not
  get. The other 268 are labelled `Price:` and have no discount block at all — there are no
  ordinary sales in this category today, only the loyalty kind. So the comparable price is
  the old one where a loyalty discount is shown, and the plain one everywhere else.
- **The JSON-LD `availability` is a constant.** It reads `InStock` for every product,
  including all 58 the listing itself marks `On order`. That is the third shop in a row
  whose structured data says the shop will sell the thing rather than that it has it, so
  the word on the card is what travels.

Because the price and the stock are on the listing and the barcode is on the product page,
**the card is written into the snapshot beside the page**, exactly as bigbox writes its
facets: a snapshot that needed a second document to be readable would not be a snapshot.
"""

import base64
import json
import re
from typing import Any

import lxml.html

from app.features.runs.channel import Listing, Part, Snapshot, register
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import Job

SLUG = "euronics-phones"
SITE = "https://www.euronics.lv"
# The English site: the Latvian path answers 404 and the shop's own analytics is in English.
CATEGORY_PATH = "/en/phones/smartphones/all-smartphones"
# The tablets' own leaf. E-readers, drawing tablets, covers and keyboards are leaves beside it,
# not inside it — unlike bigbox, whose one tablet category held all of them.
TABLETS_SLUG = "euronics-tablets"
TABLET_CATEGORY_PATH = "/en/phones/tablets/tablets"
# The sort the token names. `top` is the shop's default and the only one measured.
SORT = b"top"
# Far past the end, so one request returns the whole cumulative listing. 319 phones sat in
# 11 pages of 30 when this was written; 60 pages is 1800 products of headroom.
WHOLE_CATEGORY = 60
# A category that has outgrown the jump is a shop that changed, and it must not be read as
# a shop that shrank — see `discover`.
MORE_TO_COME = "nextAnchor"


class Euronics:
    """One channel: this shop's phones, off its pages."""

    def __init__(self, slug: str = SLUG, category_path: str = CATEGORY_PATH) -> None:
        self.slug = slug
        self.category_path = category_path

    async def discover(self, fetcher: Fetcher, job: Job) -> list[Listing]:
        """One request for the whole category, and a check that it really was the whole.

        The cheap pass stops here and has everything it needs: this listing states the
        price and the stock word for all 319 products in a single response, which is the
        least a pass over a whole shop has ever cost here.
        """
        part = await self._listing(fetcher, WHOLE_CATEGORY)
        cards = _cards(part.body)
        if not cards:
            raise ValueError(f"no products on {self.category_path}")
        if MORE_TO_COME in part.body:
            # The jump did not reach the end, so this response is a prefix of the category
            # and every product past it would be read as gone.
            raise ValueError(
                f"{self.category_path} still offers more after page {WHOLE_CATEGORY}:"
                " the category outgrew the jump"
            )
        return cards

    async def fetch(self, fetcher: Fetcher, listing: Listing) -> Snapshot:
        """The product page, and the card that sent us to it.

        Both, because neither is enough on its own: the page has the barcode and the model,
        the card has the price a shopper actually pays and whether the shop has one.
        """
        page = await fetcher.get(listing.url, role="detail")
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
        return _from_page(
            page.body,
            card=json.loads(card.body) if card else {},
            url=snapshot.url or page.url,
        )

    def read_listing(self, listing: Listing) -> dict[str, Any]:
        return dict(listing.card)

    async def _listing(self, fetcher: Fetcher, page: int) -> Part:
        return await fetcher.get(
            f"{SITE}{self.category_path}?f={_token(page)}",
            role="listing",
            headers={"Accept-Language": "en"},
        )


def _token(page: int) -> str:
    """The `?f=` cursor for a page, which is a protobuf message and not an opaque blob.

    Field 1 is the sort and field 6 is the page. Reconstructed rather than followed: the
    token this builds for page 2 is byte for byte the one the shop puts in its own `Load
    more` link, which is what says the shape was read correctly and not guessed.
    """
    message = b"\x0a" + bytes([len(SORT)]) + SORT + b"\x30" + _varint(page)
    return base64.urlsafe_b64encode(message).decode().rstrip("=")


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _cards(html: str) -> list[Listing]:
    """The listing's own record of each product.

    The brand is read and thrown away: it is `Vaikimisi` on every card in the category, and
    carrying a placeholder under the name of a brand is worse than carrying nothing.
    """
    doc = lxml.html.fromstring(html)
    cards: list[Listing] = []
    for article in doc.cssselect("[data-product-container][data-product-id]"):
        external_id = (article.get("data-product-id") or "").strip()
        link = _one(article, "a.product_name[href]")
        if not external_id or link is None:
            continue

        price, loyalty = _prices(article)
        cards.append(
            Listing(
                external_id=external_id,
                url=link.get("href") or "",
                card={
                    "id": external_id,
                    "url": link.get("href") or "",
                    "name": (article.get("data-product-name") or "").strip(),
                    # The maker's code, which this shop prints on the card and puts in the
                    # address. `sku` on the product page is the same string.
                    "mpn": (article.get("data-product-code") or "").strip(),
                    "price": price,
                    "price_loyalty": loyalty,
                    "currency": "EUR",
                    # `In stock` / `On order`, in the shop's own words.
                    "availability": _text(_one(article, ".product-card__availability")),
                    "category": (article.get("data-product-category-tree") or "").strip(),
                },
            )
        )
    return cards


def _prices(article: Any) -> tuple[str, str]:
    """What a shopper pays, and what a member pays, in that order.

    `data-product-price` is whichever of the two the card leads with, so it cannot be read
    alone. A `discount__old__loyal` block beside it means the attribute is the member's
    price and the real one is in the block.
    """
    attribute = (article.get("data-product-price") or "").strip()
    old = _one(article, ".discount__old__loyal")
    if old is None:
        return attribute, ""
    return _amount(_text(old)), attribute


def _from_page(html: str, *, card: dict[str, Any], url: str) -> dict[str, Any]:
    """The shop's own fields, from the page and the card together.

    The page's `Offer` is deliberately not read for the price or the stock: its price is
    the loyalty one on every discounted product, and its availability is `InStock` on all
    319 including the 58 the shop itself calls `On order`.
    """
    product = _product(html)
    brand = product.get("brand") or {}

    return {
        "id": card.get("id") or "",
        "url": url,
        "name": product.get("name") or card.get("name") or "",
        # Only the page has it: the card's own brand attribute is a placeholder.
        "brand": (brand.get("name") if isinstance(brand, dict) else str(brand)) or "",
        # Stated outright, which no other shop here does.
        "model": product.get("model") or "",
        "mpn": product.get("sku") or card.get("mpn") or "",
        "ean": product.get("gtin13") or "",
        "price": card.get("price") or "",
        "price_loyalty": card.get("price_loyalty") or "",
        "currency": card.get("currency") or "EUR",
        "availability": card.get("availability") or "",
        "category": product.get("category") or card.get("category") or "",
        "specs": _specs(html),
        "images": _images(html),
    }


def _product(html: str) -> dict[str, Any]:
    """The `Product` node of the page's JSON-LD graph, or nothing.

    Everything it holds is what this channel is for, but its absence is a product missing
    its barcode rather than a run that failed: the card still names the thing and its price.
    """
    doc = lxml.html.fromstring(html)
    for blob in doc.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            data = json.loads(blob)
        except ValueError:
            continue
        nodes = data.get("@graph") if isinstance(data, dict) and "@graph" in data else [data]
        for node in nodes or []:
            if isinstance(node, dict) and node.get("@type") == "Product":
                return node
    return {}


def _specs(html: str) -> dict[str, str]:
    """The specification list as the shop writes it, name to value.

    Not a table: the shop groups rows under headings, and the group is kept out of the key
    because the names here are already unique — `Screen size`, `Internal memory` — and
    prefixing them would hide them from a registry keyed on the name alone.
    """
    doc = lxml.html.fromstring(html)
    specs: dict[str, str] = {}
    for row in doc.cssselect(".specification__row"):
        name = _text(_one(row, ".specification__title")).rstrip(":")
        value = _text(_one(row, ".specification__value"))
        if name and value:
            specs.setdefault(name, value)
    return specs


def _images(html: str) -> list[str]:
    doc = lxml.html.fromstring(html)
    seen: list[str] = []
    for image in doc.cssselect(".product-gallery img[src], .product-image img[src]"):
        source = (image.get("src") or "").strip()
        if source and source not in seen:
            seen.append(source)
    return seen


def _one(doc: Any, css: str) -> Any:
    found = doc.cssselect(css)
    return found[0] if found else None


def _text(element: Any) -> str:
    return "" if element is None else " ".join(element.text_content().split())


def _amount(text: str) -> str:
    """`Regular price: 839.99 €` -> `839.99`."""
    found = re.search(r"\d[\d\s]*(?:[.,]\d+)?", text or "")
    if not found:
        return ""
    return found.group(0).replace(" ", "").replace("\xa0", "").replace(",", ".")


register(Euronics())
TABLETS_CHANNEL = register(Euronics(slug=TABLETS_SLUG, category_path=TABLET_CATEGORY_PATH))
