"""m79.lv phones, read off the shop's own listing pages.

Served from two real responses captured on 22.09.2026: a listing page at ninety-six
products, and the page that is not a listing at all. Nothing here reaches the network.
"""

import gzip
import json
import pathlib

import httpx2

from app.features.runs.channel import Part, Snapshot
from app.features.runs.channels.m79 import (
    CATEGORY_PATH,
    M79,
    PAGE_SIZE,
    SITE,
    _cards,
    _is_phone,
    _is_something_else,
    _last_page,
)
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import Job, Kind

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
LISTING = gzip.decompress((FIXTURES / "m79_listing.html.gz").read_bytes()).decode()
HIJACKED = gzip.decompress((FIXTURES / "m79_hijacked.html.gz").read_bytes()).decode()


def job(kind: Kind = Kind.FULL) -> Job:
    return Job(
        run_id=1,
        source_id=1,
        source_slug="m79-phones",
        kind=kind,
        access="retail",
        decode="markup",
        base_url=SITE,
        market_codes=["LV"],
        delivers=["catalogue", "price", "availability"],
    )


def shop(pages: dict[str, str] | None = None, asked: list | None = None) -> Fetcher:
    """Every page serves the same listing unless a path is named."""

    async def serve(request: httpx2.Request) -> httpx2.Response:
        if asked is not None:
            asked.append((request.method, str(request.url)))
        body = (pages or {}).get(request.url.path, LISTING)
        return httpx2.Response(200, text=body)

    return Fetcher(rate=0, client=httpx2.AsyncClient(transport=httpx2.MockTransport(serve)))


def discover(event_loop, pages=None, asked=None):
    return event_loop.run_until_complete(M79().discover(shop(pages, asked), job()))


def card(listings, external_id: str = "5818176296") -> dict:
    return next(x.card for x in listings if x.external_id == external_id)


# --- asking for a bigger page, and why ---


def test_the_page_size_is_asked_for_before_anything_is_read(event_loop):
    """Not a query parameter — four guesses at one were wrong. It is stored against the
    session, and it takes the walk from 314 pages to 40."""
    asked: list = []
    discover(event_loop, asked=asked)

    method, url = asked[0]
    assert method == "POST"
    assert url.endswith("/ajax/set-setting")


def test_the_paginator_names_the_last_page():
    assert _last_page(LISTING) == 40


def test_a_page_that_is_a_product_is_not_the_end_of_the_category(event_loop):
    """`/mobilie-telefoni/150` served a board game whose `Preces kods` is 150: a numeric
    path segment is looked up as a product code before it is treated as a page number, and
    a page of products goes missing without a word."""
    assert _cards(HIJACKED) == []
    listings = discover(event_loop, pages={f"{CATEGORY_PATH}/7": HIJACKED})
    # The walk carries on rather than stopping at the hole.
    assert len(listings) > 1


def test_no_products_at_all_is_an_error(event_loop):
    import pytest

    with pytest.raises(ValueError, match="no products"):
        discover(event_loop, pages={CATEGORY_PATH: HIJACKED})


# --- what one card carries ---


def test_a_card_carries_everything_a_full_pass_needs(event_loop):
    got = card(discover(event_loop))
    assert got["name"] == "Samsung Galaxy A57 5G 8/128GB Awesome Gray Mobilais Telefons"
    assert got["brand"] == "Samsung"
    assert got["price"] == "335.00"
    assert got["currency"] == "EUR"
    assert got["availability"] == "Ir veikalā"
    assert got["specs"]["Produkta krāsa"] == "Pelēks"


def test_the_item_code_is_base64_and_is_decoded(event_loop):
    """`U00tQTU3NkJaQUJFVUU` is `SM-A576BZABEUE`. Decoding is transport; what the code *is*
    — a part number, a barcode, an internal id — differs by supplier and is the reading's
    business."""
    assert card(discover(event_loop))["code"] == "SM-A576BZABEUE"


def test_the_codes_travel_as_a_list_for_the_reading_to_choose_from(event_loop):
    """Which of a shop's numbers is a barcode is decided once, for every shop, in
    `normalization/barcodes.py`."""
    with_barcode = [x for x in discover(event_loop) if x.card["barcodes"]]
    assert with_barcode, "no card in this page offered a candidate"
    assert all(isinstance(x.card["barcodes"], list) for x in discover(event_loop))


def test_every_listing_has_an_id_a_url_and_a_name(event_loop):
    listings = discover(event_loop)
    assert listings
    assert all(x.external_id and x.url and x.card["name"] for x in listings)


# --- what is filed beside a phone and is not one ---


def test_a_capacity_or_a_phone_spec_is_what_says_it_is_a_phone():
    assert _is_phone("Samsung Galaxy S26 5G 12GB/128GB Black Mobilais Telefons", {})
    # The Finnish feed writes the same unit differently, and 33 phones were lost to it.
    assert _is_phone("Nothing Phone (3) puhelin, 512/16 Gt, valkoinen Mobilais Telefons", {})
    assert not _is_phone("empower by PanzerGlass Racing USB-C to USB-C 2m sort", {})
    # No capacity anywhere, but the shop describes it as a phone.
    assert _is_phone("Evelatus Tron Dual Sim Gold", {"SIM kartes spējas": "Divas SIM kartes"})


def test_a_tablet_a_bundle_and_a_used_phone_are_left_out():
    assert _is_something_else("Samsung Galaxy Tab S11 WiFi 11 12GB 128GB Grey")
    assert _is_something_else("Xiaomi Redmi Pad 2 WiFi 11 6GB 128GB Graphite Gray")
    assert _is_something_else("Samsung Z Fold 8 Ultra + Galaxy Watch Ultra 2 LTE 12/512GB")
    assert _is_something_else("Apple iPhone 13 Pro 256GB Starlight Remade by 2BNew")
    assert not _is_something_else("Samsung Galaxy A57 5G 8/128GB Awesome Gray")


def test_the_category_is_mixed_and_the_filter_is_what_keeps_it_honest(event_loop):
    """3768 cards on the forty pages, 2691 of them phones. The rest are cases, cables,
    chargers, earbuds, a smartwatch and a VoIP desk telephone, all with `Mobilais Telefons`
    appended to their titles by the shop."""
    kept = discover(event_loop)
    names = " ".join(x.card["name"] for x in kept)
    assert "PanzerGlass" not in names
    assert len(kept) < LISTING.count('class="item" itemscope')


# --- the listing is the whole record ---


def test_nothing_is_fetched_for_a_product(event_loop):
    listing = discover(event_loop)[0]
    snapshot = event_loop.run_until_complete(M79().fetch(shop(), listing))
    assert [part.role for part in snapshot.parts] == ["card"]
    assert json.loads(snapshot.parts[0].body) == listing.card


def test_parse_reads_back_exactly_what_the_listing_said(event_loop):
    listing = discover(event_loop)[0]
    snapshot = event_loop.run_until_complete(M79().fetch(shop(), listing))
    assert M79().parse(snapshot) == listing.card
    assert M79().read_listing(listing) == listing.card


def test_a_snapshot_with_no_card_is_an_error():
    import pytest

    with pytest.raises(ValueError, match="no card"):
        M79().parse(
            Snapshot(external_id="1", parts=[Part(role="detail", url="", status=200, body="")])
        )


def test_the_page_size_is_the_one_the_shop_offers():
    assert PAGE_SIZE == 96


def test_a_reparse_cannot_readmit_what_discover_refused(event_loop):
    """A reparse reads the snapshots on disk and never calls `discover`, so a filter that
    lived only up there let seven laptops back in the first time the reader improved."""
    import pytest

    from app.features.runs.channels.m79 import CATEGORY_PATH, SITE

    laptop = Snapshot(
        external_id="1",
        parts=[
            Part(
                role="card",
                url=f"{SITE}/portativiedatori/portativie-datori-veikala/lenovo-v15",
                status=200,
                body=json.dumps(
                    {
                        "url": f"{SITE}/portativiedatori/portativie-datori-veikala/lenovo-v15",
                        "name": 'Lenovo V15 G4 AMN 15"FHD/R5-7520U/16GB/512GB SSD/DOS',
                        "specs": {},
                    }
                ),
            )
        ],
    )
    with pytest.raises(ValueError, match="not a phone"):
        M79().parse(laptop)

    # And a card from the phones section still parses.
    listing = discover(event_loop)[0]
    snapshot = event_loop.run_until_complete(M79().fetch(shop(), listing))
    assert M79().parse(snapshot)["url"].startswith(SITE + CATEGORY_PATH)


def test_a_bracketed_plus_is_the_maker_s_and_stays_on_the_model():
    """The shop's brackets hold a barcode or an edition and are cut away — all but `(Plus)`,
    which is the variant word, and cutting it filed the plus phone under the plain one."""
    from app.features.offers.normalization import read

    def model(name: str) -> str:
        return read(
            {"name": name, "brand": "Ulefone"}, source_slug="m79-phones", category="phones"
        )["model"]

    assert model("Ulefone Armor 34 (Plus) 16/512GB 5G") == "Armor 34 Plus"
    assert model("Ulefone Armor 34 Pro (Plus) 16/512GB 5G") == "Armor 34 Pro Plus"
    assert model("Ulefone Armor 34 16/512GB (6937748736236)") == "Armor 34"
