"""m79.lv phones, off the shop's own listing pages.

Written against 3737 products collected on 22.09.2026 from the category the shop calls
`Mobilie telefoni`. Two things make this shop unlike the other ten.

## The listing is the whole record

A card carries the id, the title, the price, the old price, the stock word, the shop's item
code and — for part of the catalogue — a block of specifications with the maker, the colour
and the capacity in it. Nothing is behind a product page that a reading needs, so there is
no listing-then-card split here and no cheap pass distinct from a full one: 314 pages at 12
products each and the category is read.

The product page was measured before that was decided. It adds a specification table of 113
rows — but only for the part of the catalogue the shop describes itself. The other part is a
supplier feed whose product page holds one row, and opening 3737 of them to enrich a third
would cost hours against the minutes this takes.

## Two kinds of record under one roof

The shop's own: `Samsung Galaxy A57 5G 8/128GB Awesome Gray`, short, with the spec block
filled in and the colour in Latvian.

A supplier feed's: `Samsung Galaxy Z Fold7 20.3 cm (8") Android 16.0 5G 12 GB 512 GB 4400
mAh Blue` — the whole datasheet written into the title, no spec block at all. Both are read
the same way here because both are what the shop published; sorting them out is the
ruleset's job, and the title is the same field either way.

## The barcode is in the address

There is no barcode field anywhere — not on the card, not on the product page. What there is
is the slug: `…-smf966bzsbeue-8806097423720-joinedit96318361`. Run over the 3737 slugs,
`normalization/barcodes.py` finds a valid code in **71%** of the category and **83%** of what
this channel keeps. Which of the numbers in a slug is a barcode is not decided here — the
digit runs go over as a list, as they do from dateks.

The image address holds a number too and it is **not** a barcode: on 34 sampled cards it was
13 digits once and the shop's own id the other 33 times. It is deliberately not collected.

## `data-itemid` is base64, and it is not always a part number

`data-itemid="U00tQTU3NkJaQUJFVUU"` decodes to `SM-A576BZABEUE`. It decodes on every card
sampled, and what comes out differs by supplier: Samsung's part number, Nokia's barcode
`6438409035615`, Spigen's `ACS04816`, or the shop's own `JOINEDIT96318361`. Decoding is
transport and belongs here; deciding which of those it is belongs to the reading, so it goes
over as a code and joins the barcode candidates.

## The category holds things that are not phones

`Mobilie telefoni` is where this shop also files cases, cables, chargers, earbuds, a
smartwatch and a VoIP desk telephone — and the title is no help, because the shop appends
the category name to everything: `empower by PanzerGlass Racing USB-C to USB-C 2m sort
Mobilais Telefons`.

What separates them is measured rather than guessed: a card is kept when its title states a
capacity **or** its spec block carries one of the keys only a phone has. On 46 sampled cards
that keeps 30 and drops 16, of which 12 are genuinely a cable or a charger and **none of the
30 kept is an accessory**. The four it loses are feature phones that state no capacity —
Evelatus Myriad, HMD 2660 Flip, Evelatus Tron, Panasonic KX-TU110 — and that loss is cheap
on purpose: with no capacity their identity is incomplete anyway, so they could not become a
catalogue entry even if they were collected.

## Ninety-six a page, and why that is not only about speed

The page-size control is not a query parameter — four guesses at one were wrong. It is a
`POST /ajax/set-setting` with `settingValue=96`, which stores the choice against the
`ekoshopsession` cookie; every later page then serves 96. Pages drop from 314 to 40.

The speed is the smaller half. The bigger half is that **a numeric path segment is looked up
as a product code before it is treated as a page number**: `/mobilie-telefoni/150` served a
board game whose `Preces kods` is `150`, and `/250` a toy truck. Two of five page numbers
sampled at twelve-per-page were hijacked that way, and each one silently swallows a page of
products. At ninety-six a page the walk asks for 1..40 instead of 1..314, and all forty came
back as listings when this was written. A page that comes back with no cards is still
treated as the hole it is rather than as the end of the category.

## Crawl rate

`robots.txt` asks for `Crawl-delay: 5`, which would make a pass 26 minutes. **We have the
shop's own agreement to run at the ordinary rate**, so this channel takes the shared
fetcher's pace like every other one. Do not add a private delay back on the strength of
robots.txt alone — that agreement is the reason, and it is not visible in the file.
"""

import asyncio
import base64
import binascii
import html
import json
import logging
import re
from typing import Any

import lxml.html

from app.features.runs.channel import Listing, Part, Snapshot, register
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import Job

log = logging.getLogger(__name__)

SLUG = "m79-phones"
SITE = "https://m79.lv"
CATEGORY_PATH = "/mobile-phone/mobilie-telefoni"
# Page 1 is the bare path; the rest are a number on the end. Product pages live under the
# same path with a slug rather than a number, which is why the paginator is read by digits.
LISTING = f"{SITE}{CATEGORY_PATH}"
# Where the page size is stored, against the session cookie the shop sets.
SETTING = f"{SITE}/ajax/set-setting"
PAGE_SIZE = 96
# What the shop serves when it has not been asked for more.
NARROW_PAGE = 12
_CARD_MARK = 'class="item" itemscope'

# 40 pages held 3768 products at 96 a page when this was written. The bound has to cover
# the twelve-a-page walk as well, because that is what a run gets when the shop ignores the
# setting — and a bound that fitted only the wide walk would turn that into 120 pages of a
# 314-page category, collected in silence. A category that claims more than this is a site
# that changed, not a shop that grew overnight.
MAX_PAGES = 400

_PAGE_LINK = re.compile(re.escape(CATEGORY_PATH) + r"/(\d+)(?:[/?#\"']|$)")
# `128 GB`, `8/128GB`, `4MB`. What a phone states and a cable does not. `Gt` is the same
# unit in Finnish and it is here because this shop resells a Finnish feed: 33 of its phones
# write `512/16 Gt` and were being dropped as accessories.
_CAPACITY = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:TB|GB|MB|Gt)\b", re.IGNORECASE)
# Sold in the phones category, states a capacity, and is not a phone. 19 of 2647 when this
# was written; a tablet filed as a phone is a catalogue entry nobody can tell from a real one.
_TABLET = re.compile(r"\b(?:iPad|Tablet|Galaxy Tab|Tab\s?[A-Z0-9]|[A-Za-z]*Pad)\b")
# A phone sold with a watch or earbuds in the box. 13 of 2647, and the bundle price on a
# phone's entry reads as that phone getting more expensive.
_BUNDLE = re.compile(r"\+[^+]*\b(?:Watch|Buds|Band)\b|\b(?:incl|inkl)\.", re.IGNORECASE)
# Digit runs in a slug, as candidates for a barcode. Bounded so a model number glued to
# letters — `smf966bzsbeue` — contributes nothing.
_SLUG_DIGITS = re.compile(r"(?<![0-9a-z])(\d{8,14})(?![0-9a-z])")
# Spec keys no accessory in this shop carries. Kept as fragments: the shop writes the unit
# into some of them and the entity-escaped form differs between the two record kinds.
PHONE_SPECS = ("SIM kartes", "glabātuves ietilpība", "Akumulatora ietilpība")
# Second-hand, in the four spellings this shop uses. 69 of its 1661 phones are one of them,
# and a used phone on a new phone's entry shows as that phone's cheapest price.
REFURBISHED = (
    "REMADE",
    "RENEWD",
    "PRE-OWNED",
    "MAZLIETOT",
    "(DEMO)",
    "GRADE A",
    "GRADE B",
    "GRADE C",
)


class M79:
    """One channel: this shop's phones, off its listing pages."""

    slug = SLUG

    async def discover(self, fetcher: Fetcher, job: Job) -> list[Listing]:
        first = await self._widen(fetcher)
        cards = _cards(first.body)
        if not cards:
            raise ValueError(f"no products on the first page of {CATEGORY_PATH}")

        last = min(_last_page(first.body), MAX_PAGES)
        rest = await asyncio.gather(*(self._page(fetcher, page) for page in range(2, last + 1)))

        seen: dict[str, Listing] = {}
        empty: list[int] = []
        for page, part in enumerate((first, *rest), start=1):
            found = _cards(part.body)
            if not found and page < last:
                # Not the end of the category: a page number that turned out to be a
                # product code, and a page of products nobody will see. Worth saying so.
                empty.append(page)
            for card in found:
                seen.setdefault(card.external_id, card)

        if empty:
            log.warning("m79: pages %s returned no cards — a product code took the number", empty)
        return list(seen.values())

    async def _widen(self, fetcher: Fetcher) -> Part:
        """Ask for 96 products a page instead of 12, and check that the answer took.

        Not a query parameter — there is none. The choice is stored against the session
        cookie, which the fetcher's client keeps for the whole run.

        Checked rather than trusted, because it has been observed not to take: one run
        walked the category twelve to a page while believing it was walking it ninety-six
        to a page. The page itself is the evidence — a wide page carries more than twelve
        cards — and the first page is returned so the check costs no extra request.
        """
        first = None
        for attempt in (1, 2):
            await fetcher.post(
                SETTING,
                role="setting",
                data={"settingValue": str(PAGE_SIZE)},
                headers={"X-Requested-With": "XMLHttpRequest", "Referer": LISTING},
            )
            first = await self._page(fetcher, 1)
            if first.body.count(_CARD_MARK) > NARROW_PAGE:
                return first
            log.warning("m79: the shop served %d a page on attempt %d", NARROW_PAGE, attempt)

        # Twice refused. The walk still works — there are simply more pages of fewer
        # products — and `MAX_PAGES` is set wide enough to hold them.
        return first

    async def fetch(self, fetcher: Fetcher, listing: Listing) -> Snapshot:
        """Nothing more to get: the listing is the whole record.

        A snapshot is still written, holding that record, so a re-read works exactly as it
        does for a shop whose product pages are opened one at a time.
        """
        return Snapshot(
            external_id=listing.external_id,
            parts=[
                Part(
                    role="card",
                    url=listing.url,
                    status=200,
                    body=json.dumps(listing.card, ensure_ascii=False),
                )
            ],
        )

    def parse(self, snapshot: Snapshot) -> dict[str, Any]:
        part = snapshot.part("card")
        if part is None:
            raise ValueError("snapshot has no card")
        return json.loads(part.body)

    def read_listing(self, listing: Listing) -> dict[str, Any]:
        return dict(listing.card)

    async def _page(self, fetcher: Fetcher, page: int) -> Part:
        url = LISTING if page == 1 else f"{LISTING}/{page}"
        return await fetcher.get(url, role="listing", headers={"Accept-Language": "lv"})


def _last_page(body: str) -> int:
    """The highest page the paginator names.

    The shop prints the first eleven and then a chevron straight to the last, so the maximum
    over the links is the end of the category rather than the end of a window.
    """
    return max((int(n) for n in _PAGE_LINK.findall(body)), default=1)


def _cards(body: str) -> list[Listing]:
    """What each card on the page says, in the shop's own words.

    Nothing is interpreted: the stock word travels as the shop wrote it, and the codes
    travel as a list because which of them is a barcode is not a channel's decision.
    """
    doc = lxml.html.fromstring(body)
    cards: list[Listing] = []
    for item in doc.cssselect("div.item[itemscope]"):
        external_id = (item.get("data-id") or "").strip()
        link = _one(item, 'h3 a[href], a[itemprop="url"]')
        url = (link.get("href") or "").strip() if link is not None else ""
        name = _text(_one(item, '[itemprop="name"]'))
        if not external_id or not url or not name:
            continue

        # The listing shows a few products that live in another section — seven laptops
        # among 2700 when this was written, at `/portativiedatori/`. Their own address is
        # what says so, and it is cheaper and steadier than any reading of their titles.
        if not url.startswith(SITE + CATEGORY_PATH):
            continue

        specs = _specs(item)
        if not _is_phone(name, specs) or _is_something_else(name):
            continue

        code = _code(item)
        cards.append(
            Listing(
                external_id=external_id,
                url=url,
                card={
                    "id": external_id,
                    "name": name,
                    "url": url,
                    "brand": specs.get("Ražotājs", ""),
                    "price": _text(_one(item, '[itemprop="price"]')),
                    "currency": _attr(_one(item, '[itemprop="priceCurrency"]'), "content") or "EUR",
                    "availability": _stock(item),
                    "code": code,
                    # The slug's digit runs and the item code together. `barcodes.pick`
                    # chooses, once, for every shop.
                    "barcodes": _barcodes(url, code),
                    "specs": specs,
                },
            )
        )
    return cards


def _is_phone(name: str, specs: dict[str, str]) -> bool:
    """Whether this card is a phone rather than something filed beside one.

    Measured on 46 cards: this keeps 30 and lets no accessory through. What it costs is the
    feature phones that state no capacity, which could not clear the promotion bar anyway.
    """
    if _CAPACITY.search(name):
        return True
    return any(any(key in written for key in PHONE_SPECS) for written in specs)


def _is_something_else(name: str) -> bool:
    """A card that passes the phone test and still should not be collected.

    Three kinds, all counted on the 2647 the test keeps: second-hand (a used phone on a new
    phone's entry reads as that phone's cheapest price), tablets (19), and phones sold with
    a watch or earbuds in the box (13), whose price is not the phone's price.
    """
    upper = name.upper()
    if any(word in upper for word in REFURBISHED):
        return True
    return bool(_TABLET.search(name) or _BUNDLE.search(name))


def _specs(item: Any) -> dict[str, str]:
    """The card's own specification block, as written.

    Present on the shop's own records and absent on the supplier feed's, which is a fact
    about the record rather than about the product — so an empty block is not a gap.
    """
    specs: dict[str, str] = {}
    for line in item.cssselect("div.specs li"):
        value = _text(_one(line, "b"))
        label = _text(line)
        if value and label.endswith(value):
            label = label[: -len(value)]
        label = label.rstrip(": ").strip()
        if label and value:
            specs.setdefault(label, value)
    return specs


def _code(item: Any) -> str:
    """The shop's item code, out of the base64 the add-to-cart button carries.

    Decoding is transport, like ungzipping a response. What the code *is* — a part number, a
    barcode, an internal join id — differs by supplier and is the reading's business.
    """
    raw = (_attr(_one(item, "button[data-itemid]"), "data-itemid") or "").strip()
    if not raw:
        return ""
    try:
        return base64.b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8").strip()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        # Not base64 after all. The raw value is still the shop's code for the thing, and
        # losing it would be worse than carrying it unread.
        return raw


def _barcodes(url: str, code: str) -> list[str]:
    """Every number that could be a barcode, from the address and the item code."""
    found = _SLUG_DIGITS.findall(url.rsplit("/", 1)[-1])
    if code and code.isdigit():
        found.append(code)
    seen: list[str] = []
    for value in found:
        if value not in seen:
            seen.append(value)
    return seen


def _stock(item: Any) -> str:
    """The shop's own word for what it has, kept unread.

    `Ir veikalā` is the shop floor and `Ir noliktavā` the warehouse. What each is worth is a
    reading decision and this is not the place for it.
    """
    return _text(_one(item, "div.add-to-cart button span"))


def _one(element: Any, selector: str) -> Any:
    found = element.cssselect(selector)
    return found[0] if found else None


def _text(element: Any) -> str:
    if element is None:
        return ""
    return html.unescape(" ".join(element.text_content().split())).strip()


def _attr(element: Any, name: str) -> str:
    return (element.get(name) or "") if element is not None else ""


register(M79())
