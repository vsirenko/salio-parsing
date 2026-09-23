"""1a.lv phones, through the same search index the sister shop uses.

The second shop of the Kesko Senukai group, on the same LupaSearch engine as ksenukai. Its
product pages were behind a challenge when this was written; on 23.09.2026 they answered —
ksenukai's still do not — and they carry far more than the index, so the channel reads both,
the page as an addition (see `fetch`). The reading of the index is ksenukai's, unchanged —
same field names, same shapes.

What is different is what is **missing**, measured against the sister index on 22.09.2026:

- **No barcodes at all.** ksenukai publishes `alternative_codes`; here the field is not
  there. That takes away the one signal that is proof, and leaves this shop matching on a
  part number and a model string — which is why its titles matter more than usual.
- **No `attributes_lv_*` columns.** ksenukai keeps ten extra attribute names in columns
  whose key is the name base64-encoded, `Modelis` among them. Here there are none, so the
  model has to come out of the title.
- No images, no ratings, no category ids. Everything this index has, ksenukai's has too.

What it keeps is the plain `attributes` list — with `Atmiņas ietilpība`, which the phones
ruleset already reads — and a title in the group's fixed shape:
`Mobilais telefons Samsung Galaxy S26 Ultra 5G SM-S948BZKDEUE, 256 GB, melna krās.`
"""

import contextlib
import json
from typing import Any

import lxml.html

from app.features.runs.channel import Listing, Part, Snapshot, register
from app.features.runs.channels.ksenukai import fields_of
from app.features.runs.fetching import Fetcher, FetchError
from app.features.runs.schemas import Job

SLUG = "onea-phones"
SITE = "https://www.1a.lv"
# The index key from the shop's own front end. A different key is a different shop, even
# when the engine and every field name are the same.
INDEX = "https://api.lupasearch.com/v1/query/qwxb4ncf8r99"
CATEGORY_FIELD = "categories_lv_last"
# Its own name for the section. ksenukai calls the same shelf `Mobilie telefoni`.
CATEGORIES = ("Mobilie telefoni, viedtālruņi",)
TABLETS_SLUG = "onea-tablets"
# The leaf the shop files its tablets under; the same name at both sister shops.
TABLET_CATEGORIES = ("Planšetdatori",)
PAGE = 250
MAX_PAGES = 40


class Onea:
    """One channel: this shop's phones, through its own index."""

    def __init__(self, slug: str = SLUG, categories: tuple[str, ...] = CATEGORIES) -> None:
        self.slug = slug
        self.categories = categories

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
        """The index record, and the product page beside it when the page answers.

        The index is a strict subset of the page: on 23.09.2026 a tablet's record held five
        attributes where its page held 52 — `Modelis`, `Krāsa` and the `3G`/`4G`/`5G`
        answers among them. The page is an addition, not a dependency: a challenge or an
        error leaves the record the index gave, which is all this channel had before.
        """
        parts = [
            Part(
                role="index",
                url=INDEX,
                status=200,
                body=json.dumps(listing.card, ensure_ascii=False),
            )
        ]
        with contextlib.suppress(FetchError):
            parts.append(await fetcher.get(listing.url, role="detail"))
        return Snapshot(external_id=listing.external_id, parts=parts)

    def parse(self, snapshot: Snapshot) -> dict[str, Any]:
        part = snapshot.part("index")
        if part is None:
            raise ValueError("snapshot has no index record")
        fields = fields_of(json.loads(part.body), site=SITE)
        page = snapshot.part("detail")
        if page is not None:
            fields["parameters"] = parameters(page.body)
        return fields

    def read_listing(self, listing: Listing) -> dict[str, Any]:  # pragma: no cover - no quick pass
        return fields_of(listing.card, site=SITE)

    async def _page(self, fetcher: Fetcher, offset: int) -> dict[str, Any]:
        part = await fetcher.post(
            INDEX,
            role="index",
            json={
                "searchText": "",
                "limit": PAGE,
                "offset": offset,
                "filters": {CATEGORY_FIELD: list(self.categories)},
                "modifiers": {"facets": False, "refiners": False},
            },
            headers={"Origin": SITE, "Referer": SITE + "/"},
        )
        return json.loads(part.body)


def parameters(html: str) -> dict[str, str]:
    """The page's `Izstrādājuma īpašības` table, as name -> value.

    Each name cell carries a tooltip — a sentence about what 3G is — which is prose about
    the parameter and not part of its name, so it is dropped before the cell is read. A
    page that is a challenge rather than a product has no table and reads as nothing.
    """
    try:
        doc = lxml.html.fromstring(html)
    except (ValueError, lxml.etree.ParserError):
        return {}
    found: dict[str, str] = {}
    for row in doc.cssselect("table.info-table tr"):
        cells = row.cssselect("td")
        if len(cells) != 2:
            continue
        for tip in cells[0].cssselect("div.ck-info-tooltip-wrap"):
            tip.drop_tree()
        name = " ".join(cells[0].text_content().split())
        value = " ".join(cells[1].text_content().split())
        if name and value and value != "-":
            found.setdefault(name, value)
    return found


CHANNEL = register(Onea())
TABLETS_CHANNEL = register(Onea(slug=TABLETS_SLUG, categories=TABLET_CATEGORIES))
