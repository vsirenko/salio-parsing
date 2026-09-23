"""bigbox.lv phones, read through the shop's search index.

The same third-party index service as ksenukai, a different index, and a shop that is
otherwise nothing like it: the site is a Next.js application whose listing is empty in the
HTML, and its product pages sit behind a rate limit of roughly one request a second before
Cloudflare answers 429 for ten seconds with no `Retry-After` to read.

Opening them is also unnecessary. The index carries what the specification table carries,
and the one thing only a product page holds — a long description — takes no part in
matching. So this is a **wholesale** channel like ksenukai: a few requests return the whole
category, and there is no cheap pass because the expensive one is already everything.

Its attributes are numbered rather than named: `attribute_string_466` is internal storage
and nothing in the record says so. The index names them in its facets, which are fetched
once per pass and written into every snapshot — a snapshot that needed a second document to
be readable would not be a snapshot.
"""

import json
import re
from collections.abc import Callable
from typing import Any

from app.features.runs.channel import Listing, Part, Snapshot, register
from app.features.runs.channels.tablets import is_a_tablet
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import Job

SLUG = "bigbox-phones"
TABLETS_SLUG = "bigbox-tablets"
SITE = "https://bigbox.lv"
# Taken from the shop's own front end, as with every index key. A different key is a
# different shop.
INDEX = "https://api.lupasearch.com/v1/query/gd3mh4qy0fin"
# The number in the catalogue URL, /1549-telefoni.
CATEGORY_IDS = (1549,)
# /1652-plansetdatori.
TABLET_CATEGORY_IDS = (1652,)
# Verified against the live index: 150 comes back, 200 does not.
PAGE = 150
MAX_PAGES = 40
ATTRIBUTE_PREFIX = "attribute_"


class Bigbox:
    """One channel into one of the shop's categories.

    The shop is one index with one set of facet names for every category, so a category is
    a constructor argument and not a module: its index id, and what to leave out of it.
    """

    def __init__(
        self,
        slug: str = SLUG,
        category_ids: tuple[int, ...] = CATEGORY_IDS,
        leaves_out: Callable[[str, dict[str, str]], bool] = lambda name, fields: is_a_tablet(name),
    ) -> None:
        self.slug = slug
        self.category_ids = category_ids
        self.leaves_out = leaves_out

    async def discover(self, fetcher: Fetcher, job: Job) -> list[Listing]:
        # Asked for once. The names are the same for every product in the category, and
        # asking per page would pay for them seven times over.
        names = await self._facet_names(fetcher)

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
                    url=str(item.get("product_url") or ""),
                    card={"item": item, "names": names},
                )
                for item in items
                # The phones category holds three tablets, `planšetdators` in their names,
                # and nothing else here says a card is one: a tablet collected as a phone
                # becomes a phone entry nobody can tell from a real one.
                if item.get("id") is not None
                and not self.leaves_out(_text(item.get("title")), _attributes(item, names))
            ]
            offset += len(items)
            if offset >= int(page.get("total") or 0):
                break

        return listings

    async def fetch(self, fetcher: Fetcher, listing: Listing) -> Snapshot:
        """Nothing more to get: on a wholesale channel the listing is the whole record.

        The facet names travel with it so that parsing a stored snapshot needs nothing but
        the snapshot.
        """
        return Snapshot(
            external_id=listing.external_id,
            parts=[
                Part(
                    role="index",
                    url=INDEX,
                    status=200,
                    body=json.dumps(listing.card["item"], ensure_ascii=False),
                ),
                Part(
                    role="names",
                    url=INDEX,
                    status=200,
                    body=json.dumps(listing.card["names"], ensure_ascii=False),
                ),
            ],
        )

    def parse(self, snapshot: Snapshot) -> dict[str, Any]:
        record = snapshot.part("index")
        if record is None:
            raise ValueError("snapshot has no index record")
        names_part = snapshot.part("names")
        names = json.loads(names_part.body) if names_part else {}
        item = json.loads(record.body)
        # Here as well as in `discover`: a reparse reads the snapshots on disk and never asks
        # the index again, so a filter only up there would let a mouse mat back in.
        if self.leaves_out(_text(item.get("title")), _attributes(item, names)):
            raise ValueError(f"{snapshot.external_id} is not what this channel collects")
        return _fields(item, names)

    def read_listing(self, listing: Listing) -> dict[str, Any]:  # pragma: no cover - no quick pass
        return _fields(listing.card["item"], listing.card["names"])

    async def _facet_names(self, fetcher: Fetcher) -> dict[str, str]:
        """`attribute_string_466` to `Iekšējā atmiņa, GB`, as the shop labels its filters.

        Only the filterable attributes are named; the rest keep the key the shop gave them,
        which is honest — an invented name would be our vocabulary wearing theirs.
        """
        part = await self._request(fetcher, offset=0, limit=1, facets=True)
        page = json.loads(part.body)
        return {
            str(facet["key"]): str(facet.get("label") or facet["key"]).strip()
            for facet in page.get("facets") or []
            if facet.get("key")
        }

    async def _page(self, fetcher: Fetcher, offset: int) -> dict[str, Any]:
        return json.loads((await self._request(fetcher, offset=offset, limit=PAGE)).body)

    async def _request(
        self, fetcher: Fetcher, *, offset: int, limit: int, facets: bool = False
    ) -> Part:
        return await fetcher.post(
            INDEX,
            role="index",
            json={
                "searchText": "",
                "limit": limit,
                "offset": offset,
                # Ordered explicitly. Without it the index is free to return products in a
                # different order between pages, and paging by offset then skips some and
                # repeats others.
                "sort": [{"id": "asc"}],
                "filters": {"categories_ids": list(self.category_ids)},
                "modifiers": {"facets": facets, "refiners": False},
            },
            headers={"Origin": SITE, "Referer": SITE + "/"},
        )


# A capacity in the name — `128GB`, `8/256`, `8+128` — or a memory the shop filled in.
_CAPACITY = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:TB|GB|Gt)\b|\b\d{1,2}\s*[/+]\s*\d{2,4}\b", re.I)
MEMORY_FIELDS = ("Iekšējā atmiņa, GB", "Operatīvā atmiņa, (RAM)")


def _not_a_device(name: str, fields: dict[str, str]) -> bool:
    """Whether a card in the tablet category is something that is not one.

    The category holds mouse mats, drawing tablets, keyboards, e-readers and wall displays
    beside its tablets, and the shop's own sub-categories do not tell them apart: a Wacom
    and an iPad sit under the same `Planšetdatori`. What does is that a tablet has memory.
    Measured on the first run, 23.09.2026: a card stating no capacity and filling in neither
    memory field was 43 of 580, and every one of them was not a tablet, or was a card
    titled `Acer` and nothing else.
    """
    if _CAPACITY.search(name):
        return False
    return not any(fields.get(label) for label in MEMORY_FIELDS)


def _fields(item: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    """The shop's own record, flattened, with its attributes named where it named them.

    The barcode is passed through rather than chosen: as everywhere, deciding which of a
    shop's numbers is a real GTIN is a reading decision, not a parser's.
    """
    return {
        "id": item.get("id"),
        "reference": item.get("reference"),
        "title": _text(item.get("title")),
        "url": item.get("product_url") or "",
        "brand": _text(item.get("razotaji")),
        "ean_code": item.get("ean_code"),
        "price": item.get("item_price"),
        "price_excl_vat": item.get("item_price_excl_vat"),
        "regular_price": item.get("regularPrice"),
        "currency": "EUR",
        "in_stock": item.get("in_stock"),
        "quantity": item.get("quantity"),
        "categories": item.get("categories") or [],
        "category_name": _text(item.get("kategorija")),
        "description": item.get("description"),
        "images": [item["image_url"]] if item.get("image_url") else [],
        "attributes": _attributes(item, names),
    }


def _attributes(item: dict[str, Any], names: dict[str, str]) -> dict[str, str]:
    """Every `attribute_*` the record carries, under the shop's label where there is one."""
    found: dict[str, str] = {}
    for key, value in item.items():
        if not key.startswith(ATTRIBUTE_PREFIX) or value in (None, "", []):
            continue
        name = names.get(key, key)
        found[name] = (
            "; ".join(_text(v) for v in value) if isinstance(value, list) else _text(value)
        )
    return found


def _text(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value).strip() if value is not None else ""


register(Bigbox())
# The tablet category keeps everything it is given. What else the shop files there is
# measured on the first run rather than guessed at in advance.
register(Bigbox(slug=TABLETS_SLUG, category_ids=TABLET_CATEGORY_IDS, leaves_out=_not_a_device))
