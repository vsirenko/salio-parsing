"""tet.lv phones, read off the shop's own pages.

Served from two real responses captured on 22.09.2026 — the first listing page and a
product page. Nothing here reaches the network.
"""

import gzip
import json
import pathlib

import httpx2
import pytest

from app.features.runs.channel import Part, Snapshot
from app.features.runs.channels.tet import CATEGORY_PATH, SITE, Tet
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import Job, Kind

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
LISTING = gzip.decompress((FIXTURES / "tet_listing.html.gz").read_bytes()).decode()
PRODUCT = gzip.decompress((FIXTURES / "tet_product.html.gz").read_bytes()).decode()
IPHONE = "101182"


def job(kind: Kind = Kind.FULL) -> Job:
    return Job(
        run_id=1,
        source_id=1,
        source_slug="tet-phones",
        shop_slug="tet",
        kind=kind,
        access="retail",
        decode="markup",
        base_url=SITE,
        market_codes=["LV"],
        delivers=["catalogue", "price", "availability"],
    )


def shop(body: str = LISTING, asked: list[str] | None = None) -> Fetcher:
    async def serve(request: httpx2.Request) -> httpx2.Response:
        if asked is not None:
            asked.append(str(request.url))
        return httpx2.Response(200, text=body)

    return Fetcher(rate=0, client=httpx2.AsyncClient(transport=httpx2.MockTransport(serve)))


def discover(event_loop, body: str = LISTING, asked=None):
    return event_loop.run_until_complete(Tet().discover(shop(body, asked), job()))


def card(listings, external_id: str = IPHONE) -> dict:
    return next(x.card for x in listings if x.external_id == external_id)


def product(event_loop, body: str = PRODUCT) -> dict:
    listings = discover(event_loop)
    snapshot = Snapshot(
        external_id=IPHONE,
        parts=[
            Part(role="detail", url=SITE, status=200, body=body),
            Part(
                role="card",
                url=SITE + CATEGORY_PATH,
                status=200,
                body=json.dumps(card(listings), ensure_ascii=False),
            ),
        ],
    )
    return Tet().parse(snapshot)


# --- the listing, and where it stops ---


def test_the_walk_stops_when_a_page_brings_nothing_new(event_loop):
    """Page seven is not empty and not a repeat of page six: it answers with sixty products
    the walk has already seen. Stopping on a page matching the one before it never stops."""
    asked: list[str] = []
    listings = discover(event_loop, asked=asked)

    # Every page serves the same captured body here, so the second one brings nothing new.
    assert len(asked) == 2
    assert len(listings) == 60


def test_a_page_with_no_products_is_an_error(event_loop):
    with pytest.raises(ValueError, match="no products"):
        discover(event_loop, body="<html><body><h1>Viedtālruņi</h1></body></html>")


def test_a_card_carries_what_a_cheap_pass_needs(event_loop):
    """The price, the stock flag and — unusually — the part number, with no page opened."""
    got = card(discover(event_loop))
    assert got["name"] == "Apple iPhone 18 Pro 256GB Burgundy"
    assert got["brand"] == "APPLE"
    assert got["price"] == "1499"
    assert got["mpn"] == "MJRR4HX/A"
    assert got["currency"] == "EUR"


def test_every_card_states_a_part_number(event_loop):
    listings = discover(event_loop)
    assert all(x.card["mpn"] for x in listings)


def test_a_refurbished_phone_is_left_out(event_loop):
    """`Apple iPhone 12 64GB Black Pre-owned C grade [Refurbished]` costs 198 euro and would
    attach to the entry for a new one and show as its cheapest price. Nothing here
    distinguishes condition yet."""
    listings = discover(event_loop)
    names = " ".join(x.card["name"].upper() for x in listings)
    brands = " ".join(x.card["brand"].upper() for x in listings)
    assert "RENEWD" not in brands
    assert "PRE-OWNED" not in names


def test_the_shop_says_it_in_two_languages(event_loop):
    """The Latvian word was missing at first and three used phones went through: a
    `Galaxy S24+ 512GB` at 799 euro stood as the cheapest price for a new one."""
    from app.features.runs.channels.tet import _is_refurbished

    assert _is_refurbished("Samsung Galaxy S24+ 12+512GB Amber Yellow [Mazlietots]", "SAMSUNG")
    assert not _is_refurbished("Apple iPhone 18 Pro 256GB Burgundy", "APPLE")


def test_the_stock_flag_is_the_shop_s_own_and_its_absence_is_the_answer(event_loop):
    listings = discover(event_loop)
    flags = {x.card["availability"] for x in listings}
    assert flags <= {"", "Drīzumā"}


# --- what the product page adds ---


def test_the_page_states_the_barcode(event_loop):
    read = product(event_loop)
    assert read["ean"] == "195951416649"
    assert read["mpn"] == "MJRR4HX/A"


def test_the_price_and_the_stock_flag_come_from_the_card(event_loop):
    """The page's own JSON-LD reads `InStock` for everything, including what the shop flags
    as not yet in."""
    read = product(event_loop)
    assert read["price"] == "1499"
    assert read["availability"] == ""


def test_the_specification_table_comes_over(event_loop):
    specs = product(event_loop)["specs"]
    assert specs["Krāsa"] == "Burgundijas sarkana"
    assert len(specs) > 30


def test_a_page_without_the_data_block_still_parses(event_loop):
    """Only the barcode is lost: the card names the thing and its price."""
    read = product(event_loop, body=PRODUCT.replace('id="i-product-data"', 'id="gone"'))
    assert read["ean"] == ""
    assert read["mpn"] == "MJRR4HX/A", "the card carried it too"
    assert read["price"] == "1499"


def test_a_reparse_cannot_readmit_a_used_phone(event_loop):
    """Three of them came back that way: a reparse reads the snapshots on disk and never
    calls `discover`, where the filter used to live alone."""
    listings = discover(event_loop)
    snapshot = Snapshot(
        external_id=IPHONE,
        parts=[
            Part(
                role="detail",
                url=SITE,
                status=200,
                body=PRODUCT.replace(
                    "Apple iPhone 18 Pro 256GB Burgundy",
                    "Apple iPhone 12 64GB Black Pre-owned C grade [Refurbished]",
                ),
            ),
            Part(
                role="card",
                url=SITE + CATEGORY_PATH,
                status=200,
                body=json.dumps(
                    card(listings)
                    | {"name": "Apple iPhone 12 64GB Black Pre-owned C grade [Refurbished]"},
                    ensure_ascii=False,
                ),
            ),
        ],
    )
    with pytest.raises(ValueError, match="second-hand"):
        Tet().parse(snapshot)


def test_a_snapshot_with_no_product_page_is_an_error():
    with pytest.raises(ValueError, match="no product page"):
        Tet().parse(Snapshot(external_id="1", parts=[]))


# --- the shop's own ruleset ---


def reading(event_loop, payload: dict | None = None):
    from app.features.offers.normalization import read
    from app.features.offers.normalization.rules import Vocabulary

    return read(
        payload or product(event_loop),
        source_slug="tet-phones",
        shop_slug="tet",
        category="phones",
        vocabulary=Vocabulary(
            colours={"burgundijas sarkana": "red"},
            attribute_names={"krāsa": "color", "iebūvētā atmiņa (rom)": "storage_mb"},
        ),
    )


def test_the_generic_layer_reads_the_identifiers_without_help(event_loop):
    fields = reading(event_loop)
    assert fields["gtin"] == "00195951416649"
    assert fields["mpn"] == "MJRR4HX/A"
    assert float(fields["price"]) == 1499


def test_an_absent_flag_means_in_stock(event_loop):
    """The opposite of every other channel here, which is why it is read rather than left
    to generic: 325 of 333 carry no flag at all."""
    assert reading(event_loop)["availability"] == "in_stock"
    soon = product(event_loop) | {"availability": "Drīzumā"}
    assert reading(event_loop, soon)["availability"] == "preorder"


def test_the_model_is_the_name_in_front_of_the_configuration(event_loop):
    assert reading(event_loop)["model"] == "iPhone 18 Pro"


def test_the_configuration_written_without_a_unit_is_still_a_cut(event_loop):
    """26 of the 319 write `8+256` rather than `256GB`. Reading only the second leaves
    `M8 5G 8+256 Black` as a model, which is one product per colour and per configuration."""
    poco = product(event_loop) | {"name": "Poco M8 5G 8+256 Black", "brand": "POCO"}
    assert reading(event_loop, poco)["model"] == "M8 5G"


def test_the_cut_is_the_earliest_match_and_not_the_first_one_tried(event_loop):
    """189 of the 319 write `12+256GB`. The capacity pattern finds `256GB` inside that,
    which is the middle of the configuration rather than its start — cutting there leaves
    `Galaxy S26 FE 8`, one entry per memory size."""
    samsung = product(event_loop) | {
        "name": "Samsung Galaxy S26 FE 8+128GB Graphite",
        "brand": "SAMSUNG",
    }
    assert reading(event_loop, samsung)["model"] == "Galaxy S26 FE"


def test_the_colour_comes_out_of_the_specification_table(event_loop):
    assert reading(event_loop)["identity"]["color"] == "red"


def test_the_ruleset_version_says_what_was_applied(event_loop):
    assert reading(event_loop)["ruleset_version"].startswith("generic-3+phones-16+tet-shop-1+tet-4")


def test_the_tablet_channel_walks_its_own_leaf():
    from app.features.runs.channels.tet import TABLET_CATEGORY_PATH, TABLETS_CHANNEL

    assert TABLETS_CHANNEL.slug == "tet-tablets"
    assert TABLETS_CHANNEL.category_path == TABLET_CATEGORY_PATH
    assert TABLET_CATEGORY_PATH.endswith("/plansetdatori.html")


def test_a_tablet_reads_as_the_phones_do():
    from app.features.offers.normalization import read

    fields = read(
        {"name": "Samsung Galaxy Tab S10 FE+ 8+128GB 5G Gray", "brand": "SAMSUNG"},
        source_slug="tet-tablets",
        shop_slug="tet",
        category="tablets",
    )
    assert fields["model"] == "Galaxy Tab S10 FE+"
