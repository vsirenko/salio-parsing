"""shop.cec.lv phones, read through the shop's own GraphQL.

C&C Latvija, an Apple Premium Reseller. Magento 2 with `POST /graphql` open — no key, no
signature — and the whole category in two requests, so this is a **wholesale** channel with
no listing-then-card split and no cheap pass.

**The products are not the offers; their variants are.** All twelve items in the `iPhone`
category are `ConfigurableProduct`, and each expands into the phones a shopper can actually
buy: 92 of them when this was written. Reading the twelve would file a whole family as one
product and throw away the colour and the capacity that tell its members apart.

**The variant's `sku` is Apple's own code**, `MK2D4HX/A`, which is the same string the other
shops here publish as a part number — 89 of these 92 are already in this system, carried by
up to four shops each. That matters because this shop publishes **no barcode at all**: the
GraphQL schema has no field for one. Everything it is worth rests on that code and on the
colour and capacity beside it.

**The category is resolved by its path, not pinned by its id.** `route("iphone")` returns
the uid that the product filter needs, and the uid is a base64 of an internal number that a
catalogue rebuild can change. One extra request buys a channel that survives that.

**The refurbished section is deliberately not collected.** Its four products are Apple codes
with a grade appended — `MYNF3HX/A-REFAA-BG-P` — and they are used phones. Nothing in this
system distinguishes condition yet: `offers.condition` exists and every one of the 5350
listings collected so far is `new`, while matching and the storefront ignore the column
entirely. A used iPhone 16 Pro ingested today would attach to the variant for a new one and
show as the cheapest price for it. That is a worse answer than not having it.

**Prices arrive with a double's tail.** `2389.000043` is Magento's float, not the shop's
price, and it is rounded to the cent here rather than carried into a reading.
"""

import json
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.features.runs.channel import Listing, Part, Snapshot, register
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import Job

SLUG = "cec-phones"
SITE = "https://www.shop.cec.lv"
GRAPHQL = f"{SITE}/graphql"
# The shop's path for the category this channel collects. A different category is a
# different channel; `refurbished` is deliberately not one — see the module docstring.
CATEGORY_PATH = "iphone"
# The iPads, the same configurable products under their own route.
TABLETS_SLUG = "cec-tablets"
TABLET_CATEGORY_PATH = "ipad"
# The MacBooks, one route per family. `mac` itself is not collected: it holds the iMacs, the
# Mac minis and the Studios too — 31 of its 45 products on 25.09.2026 were not laptops.
LAPTOPS_SLUG = "cec-laptops"
LAPTOP_CATEGORY_PATHS = ("mac/macbook-air", "mac/macbook-pro", "mac/macbook-neo")
# Magento answers up to 100 items per request, and twelve configurables is the whole
# category.
PAGE = 100
# A category that suddenly returns thousands is a filter that stopped filtering.
MAX_PAGES = 20

ROUTE = """
query Category($url: String!) {
  route(url: $url) {
    __typename
    ... on CategoryTree { uid name url_path product_count }
  }
}
"""

PRODUCTS = """
query Phones($uid: String!, $page: Int!, $size: Int!) {
  products(filter: {category_uid: {eq: $uid}}, pageSize: $size, currentPage: $page) {
    total_count
    items {
      __typename
      uid
      sku
      name
      url_key
      stock_status
      only_x_left_in_stock
      price_range { minimum_price { final_price { value currency } regular_price { value } } }
      ... on ConfigurableProduct {
        variants {
          product {
            uid
            sku
            name
            stock_status
            only_x_left_in_stock
            price_range { minimum_price { final_price { value currency } } }
          }
          attributes { code label value_index }
        }
      }
    }
  }
}
"""


class Cec:
    """One channel: this shop's iPhones, through its GraphQL."""

    def __init__(
        self, slug: str = SLUG, category_paths: tuple[str, ...] = (CATEGORY_PATH,)
    ) -> None:
        self.slug = slug
        self.category_paths = category_paths

    async def discover(self, fetcher: Fetcher, job: Job) -> list[Listing]:
        listings: list[Listing] = []
        for path in self.category_paths:
            found = await self._listings(fetcher, path)
            if not found:
                # One family's route that emptied is a route that moved, not a shop that
                # sold out of it; carrying on with the others would licence an absence.
                raise ValueError(f"/{path} holds nothing buyable")
            listings += found
        return listings

    async def _listings(self, fetcher: Fetcher, path: str) -> list[Listing]:
        category = await self._category(fetcher, path)
        uid = category.get("uid")
        if not uid:
            raise ValueError(f"no category at /{path}")

        listings: list[Listing] = []
        for page in range(1, MAX_PAGES + 1):
            products = await self._page(fetcher, uid, page)
            items = products.get("items") or []
            if not items:
                break
            for item in items:
                listings += _offers(item, category=category)
            if len(items) < PAGE:
                break
        return listings

    async def fetch(self, fetcher: Fetcher, listing: Listing) -> Snapshot:
        """Nothing more to get: the record from the category query is the whole record."""
        return Snapshot(
            external_id=listing.external_id,
            parts=[
                Part(
                    role="graphql",
                    url=GRAPHQL,
                    status=200,
                    body=json.dumps(listing.card, ensure_ascii=False),
                )
            ],
        )

    def parse(self, snapshot: Snapshot) -> dict[str, Any]:
        part = snapshot.part("graphql")
        if part is None:
            raise ValueError("snapshot has no product record")
        return json.loads(part.body)

    def read_listing(self, listing: Listing) -> dict[str, Any]:  # pragma: no cover - no quick pass
        return dict(listing.card)

    async def _category(self, fetcher: Fetcher, path: str) -> dict[str, Any]:
        part = await fetcher.post(
            GRAPHQL,
            role="category",
            json={"query": ROUTE, "variables": {"url": path}},
            headers={"content-type": "application/json"},
        )
        return _data(part.body).get("route") or {}

    async def _page(self, fetcher: Fetcher, uid: str, page: int) -> dict[str, Any]:
        part = await fetcher.post(
            GRAPHQL,
            role="graphql",
            json={"query": PRODUCTS, "variables": {"uid": uid, "page": page, "size": PAGE}},
            headers={"content-type": "application/json"},
        )
        return _data(part.body).get("products") or {}


def _data(body: str) -> dict[str, Any]:
    """The `data` of a GraphQL answer, or an error.

    The endpoint answers 200 and puts the failure in the body, so a query that broke looks
    from the outside exactly like a category that emptied.
    """
    parsed = json.loads(body)
    if parsed.get("errors"):
        raise ValueError(f"graphql: {json.dumps(parsed['errors'], ensure_ascii=False)[:300]}")
    return parsed.get("data") or {}


def _offers(item: dict[str, Any], *, category: dict[str, Any]) -> list[Listing]:
    """The phones a shopper can buy, out of one catalogue entry.

    A configurable is a family and its variants are its members; a simple product is its own
    single member. The family's name is carried down as the model, because that is what it
    is — `iPhone 18 Pro Max` — while the member's name repeats it with the capacity and the
    colour appended.
    """
    family = (item.get("name") or "").strip()
    url = f"{SITE}/{item.get('url_key') or ''}"
    variants = item.get("variants") or []

    if not variants:
        record = _record(item, family=family, url=url, category=category, options={})
        return [Listing(external_id=record["id"], url=url, card=record)] if record["id"] else []

    offers: list[Listing] = []
    for variant in variants:
        product = variant.get("product") or {}
        options = {
            option["code"]: (option.get("label") or "").strip()
            for option in variant.get("attributes") or []
            if option.get("code")
        }
        record = _record(product, family=family, url=url, category=category, options=options)
        if record["id"]:
            offers.append(Listing(external_id=record["id"], url=url, card=record))
    return offers


def _record(
    product: dict[str, Any],
    *,
    family: str,
    url: str,
    category: dict[str, Any],
    options: dict[str, str],
) -> dict[str, Any]:
    """The shop's own fields for one buyable phone.

    The part number goes over as `mpn` because that is what the shop's `sku` is here — the
    maker's code, not a counter of its own. There is no barcode to go with it: the schema
    has no field for one.
    """
    price = ((product.get("price_range") or {}).get("minimum_price") or {}).get("final_price") or {}
    sku = (product.get("sku") or "").strip()

    return {
        "id": sku,
        "mpn": sku,
        "url": url,
        "name": (product.get("name") or "").strip(),
        # The family this belongs to, which is the model and is stated rather than cut out
        # of anything.
        "model": family,
        "category": (category.get("name") or "").strip(),
        "price": _cents(price.get("value")),
        "currency": price.get("currency") or "EUR",
        "availability": (product.get("stock_status") or "").strip(),
        "quantity": product.get("only_x_left_in_stock"),
        # The option values as the shop labels them: `color` -> `Star White`,
        # `erply_storage` -> `256GB`. Its own codes, kept.
        "attributes": options,
    }


def _cents(value: Any) -> str:
    """`2389.000043` -> `2389.00`.

    Magento serialises its prices as doubles and the tail is the float, not the shop. It is
    taken off here rather than carried into a reading, where it would be a price nobody was
    ever asked to pay.
    """
    if value is None:
        return ""
    try:
        return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return ""


register(Cec())
TABLETS_CHANNEL = register(Cec(slug=TABLETS_SLUG, category_paths=(TABLET_CATEGORY_PATH,)))
LAPTOPS_CHANNEL = register(Cec(slug=LAPTOPS_SLUG, category_paths=LAPTOP_CATEGORY_PATHS))
