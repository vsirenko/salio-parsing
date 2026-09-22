"""bm.market phones, read through the shop's own GraphQL.

Magento 2 with `POST /graphql` open: no key, no signature, no rate limit worth the name.
200 products with every attribute come back in one request, so the whole category is 5
requests and 74 seconds and no product page is ever opened. That makes this a **wholesale**
channel like the two index-backed ones, and for the same reason: there is no
listing-then-card split to make a cheap pass out of.

**The category is `Telefoni`, not `Mobilie telefoni`.** The shop has both and the second is
the larger — 3448 against 937 — which makes it look like the right one. It is a section:
its products include Apple Watches. `Telefoni` (uid `MTIy`) is the leaf that holds phones,
and a channel collects one category.

**`stock_status` is a constant and `availability_type` is the answer.** Every product but
one reads `IN_STOCK`, which is Magento saying the shop will sell it, not that it has it.
Beside it the shop states what it means: 934 of 937 are `Pēc pasūtījuma`, to order, and 3
are `Ir veikalā`. This is a showroom that orders in, and a channel reading the first field
would report a warehouse it does not have.

**The brand is only in the selected options.** `manufacturer` is a Magento select, so
`AttributeValue.value` on it is null and the label lives in `AttributeSelectedOptions`.
Asking only for the first — which is the obvious query — loses the brand on all 937 while
appearing to work, because the attribute is present and merely empty.

**Half the catalogue carries the attribute block and half does not.** 476 of 937 have
`color`, `storage_capacity`, the RAM field and the rest of the `bm_*` specifications; the
other 461 have a name, a price and sometimes a barcode. That split runs through everything
here — barcode 50.8%, part number 45.8% — and it is the shop's, not ours: what is missing
is missing at source and the name is the only place left to read it from.
"""

import json
from typing import Any

from app.features.runs.channel import Listing, Part, Snapshot, register
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import Job

SLUG = "bm-phones"
SITE = "https://bm.market"
GRAPHQL = f"{SITE}/graphql"
# The shop's own id for the phones leaf. Part of what this channel knows, not
# configuration: a different category is a different channel. See the module docstring on
# why it is not the bigger one of the two that carry the word for telephone.
CATEGORY_UID = "MTIy"
# Verified against the live endpoint: 200 comes back whole, with every attribute, in 15
# seconds. Asking for more is where a generous endpoint stops being generous.
PAGE = 200
# A category that suddenly returns tens of thousands is a filter that stopped filtering,
# not a shop that grew overnight. 937 phones sat in 5 pages when this was written.
MAX_PAGES = 40

# Both shapes of attribute, because a select and a plain value are different types here and
# a query that asks for one silently reads nothing from the other.
QUERY = """
query Phones($uid: String!, $size: Int!, $page: Int!) {
  products(filter: {category_uid: {eq: $uid}}, pageSize: $size, currentPage: $page) {
    total_count
    items {
      __typename
      sku
      name
      url_key
      stock_status
      price_range {
        minimum_price {
          final_price { value currency }
          regular_price { value }
        }
      }
      custom_attributesV2 {
        items {
          code
          ... on AttributeValue { value }
          ... on AttributeSelectedOptions { selected_options { label value } }
        }
      }
    }
  }
}
"""

# Magento's own bookkeeping, which is on every product and describes none of them. Dropped
# rather than carried: `attributes` is what a reader looks through for a specification, and
# a `visibility` of 4 in there is noise that every rule then has to step over.
HOUSEKEEPING = frozenset(
    {
        "name",
        "price",
        "image",
        "small_image",
        "thumbnail",
        "swatch_image",
        "tier_price",
        "status",
        "visibility",
        "options_container",
        "url_key",
        "msrp_display_actual_price_type",
        "tax_class_id",
        "news_from_date",
        "news_to_date",
        "custom_design_to",
        "gift_message_available",
        "skip_translation",
        "skip_ai_description",
        "no_index",
    }
)

# Read into fields of their own rather than left in the attribute table.
BRAND = "manufacturer"
BARCODE = "ean_barcode"
PART_NUMBER = "mpn"
AVAILABILITY = "availability_type"
DELIVERY = "delivery_time"
COLOUR = "color"


class Bm:
    """One channel: this shop's phones, through its GraphQL."""

    slug = SLUG

    async def discover(self, fetcher: Fetcher, job: Job) -> list[Listing]:
        listings: list[Listing] = []
        for page in range(1, MAX_PAGES + 1):
            products = await self._page(fetcher, page)
            items = products.get("items") or []
            if not items:
                break

            listings += [
                Listing(
                    external_id=str(item["sku"]),
                    url=f"{SITE}/{item.get('url_key') or ''}",
                    card=item,
                )
                for item in items
                if item.get("sku")
            ]
            if len(listings) >= int(products.get("total_count") or 0):
                break

        return listings

    async def fetch(self, fetcher: Fetcher, listing: Listing) -> Snapshot:
        """Nothing more to get: on a wholesale channel the listing is the whole record.

        A snapshot is still written, holding that record, so a re-read works exactly as it
        does for a shop whose cards are fetched one at a time.
        """
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
        return fields_of(json.loads(part.body))

    def read_listing(self, listing: Listing) -> dict[str, Any]:  # pragma: no cover - no quick pass
        return fields_of(listing.card)

    async def _page(self, fetcher: Fetcher, page: int) -> dict[str, Any]:
        part = await fetcher.post(
            GRAPHQL,
            role="graphql",
            json={"query": QUERY, "variables": {"uid": CATEGORY_UID, "size": PAGE, "page": page}},
            headers={"content-type": "application/json"},
        )
        body = json.loads(part.body)
        # GraphQL answers 200 and puts the failure in the body, so a query that broke looks
        # from the outside exactly like a category that emptied.
        if body.get("errors"):
            raise ValueError(f"graphql: {json.dumps(body['errors'], ensure_ascii=False)[:300]}")
        return (body.get("data") or {}).get("products") or {}


def fields_of(item: dict[str, Any]) -> dict[str, Any]:
    """The shop's own record, flattened and nothing more.

    Deliberately not our shape. The barcode goes over as the shop wrote it and is not
    validated here — check digits are a standard and `normalization/barcodes.py` is where
    that is applied once for every shop. The shop's own number goes over as `id` and never
    as `sku`, which is a name the generic reader takes for a manufacturer's part number.
    """
    attributes = _attributes(item)
    price = ((item.get("price_range") or {}).get("minimum_price") or {}).get("final_price") or {}
    regular = ((item.get("price_range") or {}).get("minimum_price") or {}).get(
        "regular_price"
    ) or {}

    return {
        "id": item.get("sku"),
        "name": item.get("name") or "",
        "url": f"{SITE}/{item.get('url_key') or ''}",
        "brand": _label(attributes.pop(BRAND, None)),
        "ean": _label(attributes.pop(BARCODE, None)),
        "mpn": _label(attributes.pop(PART_NUMBER, None)),
        "price": price.get("value"),
        "currency": price.get("currency") or "EUR",
        "old_price": regular.get("value"),
        # The shop's own words for what it has, which is not what `stock_status` says.
        "availability": _label(attributes.pop(AVAILABILITY, None)),
        "delivery": _label(attributes.pop(DELIVERY, None)),
        # Carried because it is the shop's own claim and a stored payload should hold what
        # arrived, under a name nothing reads as an answer.
        "stock_status": item.get("stock_status") or "",
        "color": _label(attributes.get(COLOUR)),
        "attributes": attributes,
    }


def _attributes(item: dict[str, Any]) -> dict[str, str]:
    """Every custom attribute the shop set, by its own code.

    The codes are the shop's — `bm_operativa_atmina_545` is the working memory and nothing
    in the record says so, exactly as bigbox numbers its own. They keep the name the shop
    gave them, because an invented one would be our vocabulary wearing theirs.
    """
    found: dict[str, str] = {}
    for attribute in (item.get("custom_attributesV2") or {}).get("items") or []:
        code = attribute.get("code")
        if not code or code in HOUSEKEEPING:
            continue
        if "value" in attribute:
            value = _text(attribute.get("value"))
        else:
            value = "; ".join(
                _text(option.get("label"))
                for option in attribute.get("selected_options") or []
                if _text(option.get("label"))
            )
        if value:
            found[code] = value
    return found


def _label(value: Any) -> str:
    return _text(value)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        value = "; ".join(str(v) for v in value if v is not None)
    return str(value).strip()


register(Bm())
