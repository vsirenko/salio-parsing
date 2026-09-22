"""ksenukai.lv phones, read through the shop's search index.

The shop itself is behind Cloudflare: catalogue pages answer with a challenge and its own
API is disallowed, so there are no product pages and no images for a robot. Everything
needed is in the index its own front end queries — LupaSearch, a third-party service the
shop pushes its catalogue into.

That makes this a **wholesale** channel: a few requests return the whole category, there is
no listing-then-card split, and therefore no cheap pass — which the source's own
constraints already refuse to let anyone configure.

What the index does not have is the full specification table; only the filterable
attributes are there. That is tolerable rather than ideal: attributes reach a product from
other shops through a shared barcode.
"""

import base64
import json
from typing import Any

from app.features.runs.channel import Listing, Part, Snapshot, register
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import Job

SLUG = "ksenukai-phones"
SITE = "https://www.ksenukai.lv"
# The index key is taken from the shop's own front end. It is part of what this channel
# knows, not configuration: a different key is a different shop.
INDEX = "https://api.lupasearch.com/v1/query/15s471huw5im"
# The filterable field holding the names of the catalogue leaves a product sits in.
CATEGORY_FIELD = "categories_lv_last"
# Filterable attributes live in columns whose name is base64 in the key itself.
COLUMN_PREFIX = "attributes_lv_"
CATEGORIES = ("Mobilie telefoni",)
# Verified against the live index: 250 comes back, and more is not needed.
PAGE = 250
# A category that suddenly returns thousands of items is a filter that stopped filtering,
# not a shop that grew overnight. Stopping is better than collecting the whole shop.
MAX_PAGES = 40


class Ksenukai:
    """One channel: this shop's phones, through this index."""

    slug = SLUG

    async def discover(self, fetcher: Fetcher, job: Job) -> list[Listing]:
        listings: list[Listing] = []
        offset = 0
        for _ in range(MAX_PAGES):
            page = await self._page(fetcher, offset)
            items = page.get("items") or []
            if not items:
                break

            listings += [
                Listing(
                    external_id=str(item["id"]),
                    url=SITE + (item.get("url_lv") or ""),
                    card=item,
                )
                for item in items
                if item.get("id") is not None
            ]
            offset += len(items)
            if offset >= int(page.get("total") or 0):
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
                    role="index",
                    url=INDEX,
                    status=200,
                    body=json.dumps(listing.card, ensure_ascii=False),
                )
            ],
        )

    def parse(self, snapshot: Snapshot) -> dict[str, Any]:
        part = snapshot.part("index")
        if part is None:
            raise ValueError("snapshot has no index record")
        return fields_of(json.loads(part.body))

    def read_listing(self, listing: Listing) -> dict[str, Any]:  # pragma: no cover - no quick pass
        return fields_of(listing.card)

    async def _page(self, fetcher: Fetcher, offset: int) -> dict[str, Any]:
        part = await fetcher.post(
            INDEX,
            role="index",
            json={
                "searchText": "",
                "limit": PAGE,
                "offset": offset,
                "filters": {CATEGORY_FIELD: list(CATEGORIES)},
                # Facets and refiners are the shop's filter sidebar. We do not draw one,
                # and asking for them makes every page heavier for nothing.
                "modifiers": {"facets": False, "refiners": False},
            },
            headers={
                # The index answers for a shop, and the origin is how it knows which.
                "Origin": SITE,
                "Referer": SITE + "/",
            },
        )
        return json.loads(part.body)


def fields_of(item: dict[str, Any], *, site: str = SITE) -> dict[str, Any]:
    """The shop's own record, flattened and nothing more.

    Shared with `onea`, the group's other shop: same engine, same field names, same shapes,
    and a sister index that is a strict subset of this one. Copying it there would be two
    copies of one decision about what a Kesko record looks like, drifting apart the first
    time either shop adds a field.

    Deliberately not our shape. In particular the barcode is **not** picked out of
    `alternative_codes` here: that list mixes barcodes with the shop's internal numbering,
    and choosing between them is a reading decision — check digits and reserved prefixes
    are a standard, not something this shop invented. Doing it in the parser would bake one
    interpretation into the only copy of the bytes there is, and every other channel would
    then have to make the same decision separately and differently.
    """
    prices = item.get("prices") or []
    return {
        "id": item.get("id"),
        "title": _text(item.get("title_lv")),
        "url": site + (item.get("url_lv") or ""),
        "brand": _text(item.get("brand_lv")),
        "product_code": item.get("product_code"),
        "article_number": item.get("article_number"),
        "alternative_codes": item.get("alternative_codes") or [],
        "price": item.get("price_default"),
        "price_loyalty": item.get("price_loyalty"),
        # The shop's own currency, which it does not state: the whole catalogue is euro.
        "currency": "EUR",
        "old_price": next(
            (p.get("compare_at_price") for p in prices if p.get("compare_at_price")), None
        ),
        "in_stock": item.get("in_stock"),
        "categories": item.get("categories_lv_last") or [],
        "product_type": _text(item.get("product_type_lv")),
        "description": item.get("description_lv"),
        "images": item.get("images") or ([item["image"]] if item.get("image") else []),
        "attributes": _attributes(item),
    }


def _attributes(item: dict[str, Any]) -> dict[str, str]:
    """The Latvian attribute table as the shop writes it, name to value.

    Read from **both** places the index keeps attributes in, because neither is a superset
    of the other. Measured over all 520 phones on 21.09.2026:

    - the `attributes` list holds five names, with units, led by screen size and memory;
    - the `attributes_lv_*` columns beside it hold ten names that the list does not have at
      all — and one of them is `Modelis`, present on 100% of products. The model is what
      brand-and-model matching stands on, so reading only the list would throw away the
      one field this channel is most useful for.

    Those columns carry their name base64-encoded into the field key, which is a shape for
    the shop's own faceted search rather than anything meant to be read. Their names are
    also dirtier: screen size arrives as `Ekrāna izmērs, "`. The list wins where both have
    a name, because it carries the unit separately.

    A name that appears twice has its values joined rather than overwritten: about a third
    of these products list `Aizmugurējā kamera` more than once, and keeping the last would
    quietly drop half of what the shop said about their cameras.
    """
    found: dict[str, str] = {}

    def add(name: str, value: str) -> None:
        if not name or not value:
            return
        if name in found and value not in found[name].split("; "):
            found[name] = f"{found[name]}; {value}"
        else:
            found.setdefault(name, value)

    for attribute in item.get("attributes") or []:
        unit = _text((attribute.get("unit") or {}).get("lv")) if attribute.get("unit") else ""
        value = _text((attribute.get("value") or {}).get("lv"))
        add(_text((attribute.get("name") or {}).get("lv")), f"{value} {unit}".strip())

    for key, value in item.items():
        if not key.startswith(COLUMN_PREFIX):
            continue
        name = _decode(key)
        if name is None or name in found:
            continue
        add(name, "; ".join(_text(v) for v in value) if isinstance(value, list) else _text(value))

    return found


def _decode(key: str) -> str | None:
    """`attributes_lv_str_TW9kZWxpcw==` to `Modelis`, or nothing if it is not a name."""
    encoded = key.rsplit("_", 1)[-1]
    try:
        return base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8").strip() or None
    except (ValueError, UnicodeDecodeError):
        return None


def _text(value: Any) -> str:
    """The index gives some fields as a single-item list and some as a string."""
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value).strip() if value is not None else ""


register(Ksenukai())
