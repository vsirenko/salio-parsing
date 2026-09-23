"""discover.lv phones, read out of the shop's own export.

**One request is the whole shop.** `/catalog.xml` is 2768 products and 1.2 MB, with no key
and no header, and 560 of them are phones. There is no listing to page through and no
product page to open, which makes this a **wholesale** channel and the cheapest one here by
a distance — the full pass costs a single GET.

**The product page is deliberately not opened.** It carries a specification table and a
price inside a leasing calculator, and nothing this channel needs: the name already states
the capacity and the colour, and there is **no barcode on it or anywhere else on this
shop**. Opening 560 pages to collect a table nobody reads is 560 requests for nothing. It is
also encoded windows-1257 with no charset header, which is a trap this channel gets to
avoid entirely by not going there.

**The brand is the section, and the section has HTML in it.** `category_full` reads
`Mobilie telefoni >> Samsung`, and for one maker `Mobilie telefoni >> <b>Apple` — a bold tag
that leaked out of the shop's own page and into its export. Carried over as it stands it is
a brand nobody can resolve, so the tags come off.

**`in_stock` is `1` on every one of the 560**, which is not a field worth reading and is a
fact worth knowing: the export holds what the shop is willing to sell, so presence in it
*is* the availability. A product that leaves the feed has left the shop — which is exactly
the absence inference the run contract gates, and the reason it matters that this channel
either returns all 560 or fails.

**The code in brackets is a family, not a product.** 228 names carry one — `(SM-S948B)` —
and the same string covers every colour and capacity of that phone, so it is a product line
and not a part number. It goes over under its own name and the ruleset files it as a line;
offered as `mpn` it would send the part-number rung looking for one thing and finding nine.
"""

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import Any

from app.features.runs.channel import Listing, Part, Snapshot, register
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import Job

SLUG = "discover-phones"
SITE = "https://www.discover.lv"
FEED = f"{SITE}/catalog.xml"
# The section this channel collects, as the export spells it. A different section is a
# different channel.
CATEGORY_PREFIX = "Mobilie telefoni"
# A feed that suddenly holds tens of thousands is a shop that changed, not one that grew.
MAX_ITEMS = 20000

# The shop's own product number, which is the last segment of every link.
_ID = re.compile(r"/(\d+)/?$")
# A bold tag that leaked out of the shop's page and into its export.
_TAGS = re.compile(r"<[^>]+>")
# `Samsung Galaxy S26 Ultra 512GB (SM-S948B) Titanium Silver` — the maker's designation for
# the family, in brackets and anywhere in the name.
_FAMILY = re.compile(r"\(([A-Z][A-Z0-9][A-Z0-9/–-]{2,})\)")


class Discover:
    """One channel: this shop's phones, out of its export."""

    def __init__(
        self,
        slug: str = SLUG,
        selects: Callable[[str, str], bool] | None = None,
        maker_of: Callable[[str], str] | None = None,
    ) -> None:
        self.slug = slug
        self.selects = selects or _a_phone
        self.maker_of = maker_of or _maker_from_section

    async def discover(self, fetcher: Fetcher, job: Job) -> list[Listing]:
        part = await fetcher.get(FEED, role="feed")
        records = _records(part.body, self.selects, self.maker_of)
        if not records:
            # The export answered and holds nothing of this channel's. That is a section
            # that was renamed, not a shop that sold out, and reporting none would licence
            # an absence.
            raise ValueError(f"no products for {self.slug} in the export")
        return [
            Listing(external_id=record["id"], url=record["url"], card=record) for record in records
        ]

    async def fetch(self, fetcher: Fetcher, listing: Listing) -> Snapshot:
        """Nothing more to get: the export record is the whole record.

        A snapshot is still written, holding it, so a re-read works exactly as it does for
        a shop whose cards are fetched one at a time.
        """
        return Snapshot(
            external_id=listing.external_id,
            parts=[
                Part(
                    role="feed",
                    url=FEED,
                    status=200,
                    body=json.dumps(listing.card, ensure_ascii=False),
                )
            ],
        )

    def parse(self, snapshot: Snapshot) -> dict[str, Any]:
        part = snapshot.part("feed")
        if part is None:
            raise ValueError("snapshot has no export record")
        return json.loads(part.body)

    def read_listing(self, listing: Listing) -> dict[str, Any]:  # pragma: no cover - no quick pass
        return dict(listing.card)


def _a_phone(section: str, name: str) -> bool:
    return section.startswith(CATEGORY_PREFIX)


def _maker_from_section(section: str) -> str:
    """The section after the separator is the maker: `Mobilie telefoni >> Samsung`."""
    return _plain(section.split(">>")[-1])


# The tablets have no section of their own. They share `Portatīvie/Planšetdatori` with a
# laptop (122 of 123 on 23.09.2026) and `Apple` with MacBooks, iMacs and a Pencil (100 of 137
# are iPads).
MIXED_SECTION = "Datortehnika >> Portatīvie/Planšetdatori"
APPLE_SECTION = "Datortehnika >> Apple"
_LAPTOP = re.compile(r"\b(?:Laptop|MacBook|Notebook)\b", re.IGNORECASE)
_IPAD = re.compile(r"\biPad\b", re.IGNORECASE)


def a_tablet(section: str, name: str) -> bool:
    if section == MIXED_SECTION:
        return not _LAPTOP.search(name)
    return section == APPLE_SECTION and bool(_IPAD.search(name))


def tablet_maker(section: str) -> str:
    """`Apple` where the section names it; nothing where the section is a kind of thing,
    and the matcher reads the maker off the name — `Samsung Galaxy Tab S10 FE …`."""
    return "Apple" if section == APPLE_SECTION else ""


def _records(
    xml: str, selects: Callable[[str, str], bool], maker_of: Callable[[str], str]
) -> list[dict[str, Any]]:
    """Every product of this channel in the export, as the shop wrote it.

    The whole export is parsed and then filtered rather than filtered while parsing: the
    section names are the shop's and reading them all is what makes a renamed one visible
    instead of silently empty.
    """
    root = ET.fromstring(xml)
    records: list[dict[str, Any]] = []
    for item in list(root)[:MAX_ITEMS]:
        fields = {child.tag: (child.text or "").strip() for child in item}
        section = _plain(fields.get("category_full"))
        if not selects(section, _plain(fields.get("name"))):
            continue

        link = (fields.get("link") or "").strip()
        found = _ID.search(link)
        if not found:
            continue

        name = _plain(fields.get("name"))
        family = _FAMILY.search(name)
        records.append(
            {
                "id": found.group(1),
                "url": link,
                "name": name,
                # The section after the separator is the maker. The tags come off: one of
                # them arrives as `<b>Apple`.
                "brand": maker_of(section),
                "category": section,
                "price": (fields.get("price") or "").strip(),
                "currency": "EUR",
                # `1` on all 560. Kept as the shop wrote it rather than read as an answer —
                # what it really says is that the product is in the export at all.
                "in_stock": (fields.get("in_stock") or "").strip(),
                # The maker's designation for the family, not for this phone.
                "line": family.group(1) if family else "",
                "image": (fields.get("image") or "").strip(),
            }
        )
    return records


def _plain(value: str | None) -> str:
    """The shop's text with the HTML it exported by accident taken out."""
    return " ".join(_TAGS.sub(" ", value or "").split())


register(Discover())
TABLETS_SLUG = "discover-tablets"
TABLETS_CHANNEL = register(Discover(slug=TABLETS_SLUG, selects=a_tablet, maker_of=tablet_maker))
