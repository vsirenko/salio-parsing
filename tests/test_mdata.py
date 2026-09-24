"""mdata.lv phones, read off the shop's own pages.

Served from two real responses captured on 22.09.2026 — the first listing page and a
product page. Nothing here reaches the network.
"""

import gzip
import json
import pathlib

import httpx2
import pytest

from app.features.runs.channel import Part, Snapshot
from app.features.runs.channels.mdata import SITE, MData, _cards, _from_page, _last_page
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import Job, Kind

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
LISTING = gzip.decompress((FIXTURES / "mdata_listing.html.gz").read_bytes()).decode()
PRODUCT = gzip.decompress((FIXTURES / "mdata_product.html.gz").read_bytes()).decode()
IPHONE = "363827"


def job(kind: Kind = Kind.FULL) -> Job:
    return Job(
        run_id=1,
        source_id=1,
        source_slug="mdata-phones",
        shop_slug="mdata",
        kind=kind,
        access="retail",
        decode="markup",
        base_url=SITE,
        market_codes=["LV"],
        delivers=["catalogue", "price", "availability"],
    )


def shop(body: str = LISTING, asked: list | None = None) -> Fetcher:
    async def serve(request: httpx2.Request) -> httpx2.Response:
        if asked is not None:
            asked.append(str(request.url))
        return httpx2.Response(200, text=body)

    return Fetcher(rate=0, client=httpx2.AsyncClient(transport=httpx2.MockTransport(serve)))


def discover(event_loop, body: str = LISTING, asked=None):
    return event_loop.run_until_complete(MData().discover(shop(body, asked), job()))


def card() -> dict:
    return next(c.card for c in _cards(LISTING) if c.external_id == IPHONE)


# --- the listing ---


def test_the_paginator_names_the_last_page():
    assert _last_page(LISTING) == 8


def test_a_page_with_no_products_is_an_error(event_loop):
    with pytest.raises(ValueError, match="no products"):
        discover(event_loop, body="<html><body><h1>Mobilie telefoni</h1></body></html>")


def test_a_first_page_of_second_hand_stock_is_not_an_empty_category(event_loop):
    """On 23.09.2026 all 48 cards on the first page were demo stock. The filter dropped them,
    as it should, and the run failed as if the category were gone."""
    import re

    demo = re.sub(r'alt="([^"]+)"', r'alt="\1 Demo"', LISTING)

    async def serve(request: httpx2.Request) -> httpx2.Response:
        first = "/page/1/" in str(request.url)
        return httpx2.Response(200, text=demo if first else LISTING)

    fetcher = Fetcher(rate=0, client=httpx2.AsyncClient(transport=httpx2.MockTransport(serve)))
    listings = event_loop.run_until_complete(MData().discover(fetcher, job()))
    assert listings, "the new phones on the later pages are collected"
    assert not any("Demo" in x.card["name"] for x in listings)


def test_a_card_carries_what_the_cheap_pass_needs():
    got = card()
    assert got["name"].startswith("MOBILE PHONE IPHONE 15")
    assert got["brand"] == "APPLE"
    assert got["prices"] == ["751.28"]
    assert got["currency"] == "EUR"


def test_second_hand_stock_is_left_out():
    """237 of this shop's 332 phones are `Demo` or `Renew` — it sells refurbished as its
    main trade. Nothing here tells conditions apart yet, and a refurbished phone on a new
    one's entry shows as that phone's cheapest price."""
    kept = _cards(LISTING)
    names = " ".join(c.card["name"].upper() for c in kept)
    assert "DEMO" not in names
    assert "RENEW" not in names
    # And the page really did offer them: 47 of its 51 cards.
    assert len(kept) < LISTING.count('class="product_box_listing')


def test_how_soon_is_read_from_the_badge_class_not_its_words():
    """Every card carries the same five labels, because they are the legend rather than the
    answer. The class picks which one applies."""
    assert card()["availability"] == "1-2 days"


# --- what the product page adds ---


def test_the_page_states_the_barcode_and_the_part_number():
    """The shop has two of its own fields the wrong way round: `model` holds the barcode and
    `mpn` an internal number, and the maker's code is in the prose of the description."""
    fields = _from_page(PRODUCT, card=card())
    assert "195949036064" in fields["barcodes"]
    assert fields["mpn"] == "MTP03ZD/A"


def test_the_codes_travel_as_a_list_for_the_reading_to_choose_from():
    """Which of a shop's numbers is a barcode is decided once, for every shop."""
    fields = _from_page(PRODUCT, card=card())
    assert isinstance(fields["barcodes"], list)
    assert "1405626" in fields["barcodes"], "the internal number goes over too, unjudged"


def test_the_specification_comes_over_one_fact_to_a_line():
    specs = _from_page(PRODUCT, card=card())["specs"]
    assert specs["Model"] == "iPhone 15"
    assert specs["Built-in Memory"] == "128 GB"
    # A bare line is kept under its own text, because a colour arrives that way.
    assert "Black" in specs


def test_a_colour_and_a_storage_line_are_split_into_name_and_value():
    """`Colour Black/Green` was kept whole as its own name, and nothing looking a field up by
    its name could find the colour inside it."""
    from app.features.runs.channels.mdata import _specs

    specs = _specs("Colour Black/Green\nStorage 128 GB\nNetwork 4G")
    assert specs["Colour"] == "Black/Green"
    assert specs["Storage"] == "128 GB"
    assert specs["Network 4G"] == "Network 4G"


def test_the_price_is_the_one_that_is_charged():
    """A card on sale prints the price before the discount first and the one you pay
    second."""
    fields = _from_page(PRODUCT, card=card() | {"prices": ["399.99", "269.99"]})
    assert fields["price"] == "269.99"


def test_a_snapshot_with_no_product_page_is_an_error():
    with pytest.raises(ValueError, match="no product page"):
        MData().parse(Snapshot(external_id="1", parts=[]))


def test_a_reparse_cannot_readmit_a_second_hand_phone():
    """A reparse reads the snapshots on disk and never calls `discover`, where the filter
    would otherwise live alone."""
    snapshot = Snapshot(
        external_id=IPHONE,
        parts=[
            Part(
                role="detail",
                url=SITE,
                status=200,
                # A slash inside the name is escaped in the JSON, so the piece replaced
                # here is one that reads the same in the markup and in the block.
                body=PRODUCT.replace("128GB BLACK", "128GB BLACK Demo"),
            ),
            Part(role="card", url=SITE, status=200, body=json.dumps(card(), ensure_ascii=False)),
        ],
    )
    with pytest.raises(ValueError, match="second-hand"):
        MData().parse(snapshot)


def test_a_second_hand_product_the_name_does_not_admit_is_left_out():
    """All 20 tablets and 8 phones said it only in the page's property table."""
    row = (
        '<div class="product_property_wrapper"><div class="product_option_name"> Stāvoklis:'
        ' </div><div class="product_option_value">Renew (Atjaunots) </div></div>'
    )

    def page(body: str) -> Snapshot:
        return Snapshot(
            external_id=IPHONE,
            parts=[
                Part(role="detail", url=SITE, status=200, body=body),
                Part(
                    role="card", url=SITE, status=200, body=json.dumps(card(), ensure_ascii=False)
                ),
            ],
        )

    with pytest.raises(ValueError, match="second-hand"):
        MData().parse(page(PRODUCT.replace("</body>", row + "</body>")))
    # A new product's page has no such row, or another state in it, and is read.
    assert MData().parse(page(PRODUCT))["name"]


# --- the shop's own ruleset ---


def reading(payload: dict | None = None):
    from app.features.offers.normalization import read
    from app.features.offers.normalization.rules import Vocabulary

    return read(
        payload or _from_page(PRODUCT, card=card()),
        source_slug="mdata-phones",
        shop_slug="mdata",
        category="phones",
        vocabulary=Vocabulary(colours={"black": "black", "white": "white"}),
    )


def test_the_barcode_is_picked_out_of_the_numbers_the_shop_mislabelled():
    """`model` holds the barcode here and `mpn` an internal number, so nothing is trusted by
    the name of the field it arrived in."""
    assert reading()["gtin"] == "00195949036064"


def test_how_soon_reads_as_in_stock():
    """This shop says how soon rather than whether, and all three of its words mean the
    thing can be bought."""
    assert reading()["availability"] == "in_stock"
    soon = _from_page(PRODUCT, card=card() | {"availability": "3-5 days"})
    assert reading(soon)["availability"] == "in_stock"


def test_the_model_the_shop_states_is_taken_as_it_stands():
    """65 of the 98 carry `Model iPhone 15` as a field, which beats any cut of a title."""
    assert reading()["model"] == "iPhone 15"


def test_a_record_the_shop_never_described_is_cut_at_the_configuration():
    """The other 33 have nothing but the barcode, the part number and the warranty. This
    shop writes the configuration as `6/ 256GB` as well as `128GB`, and the earliest match
    is the cut — otherwise `ARMOR MINI 20/ 6` becomes a model of its own."""
    bare = _from_page(PRODUCT, card=card()) | {
        "specs": {"EAN": "6975326668262"},
        "name": "MOBILE PHONE ARMOR MINI 20/ 6/ 256GB BLACK ULEFONE Mobilais telefons",
        "brand": "ULEFONE",
    }
    assert reading(bare)["model"] == "MOBILE PHONE ARMOR MINI 20"


def test_the_ruleset_version_says_what_was_applied():
    assert reading()["ruleset_version"].startswith("generic-3+phones-13+mdata-shop-1+mdata-4")


def test_the_tablet_channel_asks_for_its_own_category():
    from app.features.runs.channels.mdata import TABLET_CATEGORY, TABLETS_CHANNEL

    assert TABLETS_CHANNEL.slug == "mdata-tablets"
    assert TABLETS_CHANNEL.category == TABLET_CATEGORY == 556
