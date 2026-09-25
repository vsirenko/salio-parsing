"""euronics.lv phones, read off the shop's own pages.

Served from two real responses captured on 22.09.2026 — the whole category in one listing
response, and a product page — kept compressed because they are 2 MB and 350 KB of real
markup. Nothing here reaches the network.
"""

import gzip
import json
import pathlib

import httpx2
import pytest

from app.features.runs.channel import Part, Snapshot
from app.features.runs.channels.euronics import SITE, Euronics, _token
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import Job, Kind

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
LISTING = gzip.decompress((FIXTURES / "euronics_listing.html.gz").read_bytes()).decode()
PRODUCT = gzip.decompress((FIXTURES / "euronics_product.html.gz").read_bytes()).decode()
# The Samsung the product page belongs to, and the one card that is discounted for members.
SAMSUNG = "166473"


def job(kind: Kind = Kind.FULL) -> Job:
    return Job(
        run_id=1,
        source_id=1,
        source_slug="euronics-phones",
        shop_slug="euronics",
        kind=kind,
        access="retail",
        decode="json_ld",
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
    return event_loop.run_until_complete(Euronics().discover(shop(body, asked), job()))


def card(listings, external_id: str = SAMSUNG) -> dict:
    return next(listing.card for listing in listings if listing.external_id == external_id)


def product(event_loop, body: str = PRODUCT) -> dict:
    listings = discover(event_loop)
    snapshot = Snapshot(
        external_id=SAMSUNG,
        url=card(listings)["url"],
        parts=[
            Part(role="detail", url=card(listings)["url"], status=200, body=body),
            Part(
                role="card",
                url=SITE,
                status=200,
                body=json.dumps(card(listings), ensure_ascii=False),
            ),
        ],
    )
    return Euronics().parse(snapshot)


# --- one request for the whole category ---


def test_the_token_is_the_shop_s_own_and_not_a_guess():
    """Field 1 is the sort and field 6 is the page. The token this builds for page 2 is
    byte for byte the one the shop puts in its own `Load more` link."""
    assert _token(2) == "CgN0b3AwAg"


def test_the_whole_category_arrives_in_one_response(event_loop):
    asked: list[str] = []
    listings = discover(event_loop, asked=asked)

    assert len(asked) == 1, "the pages are cumulative, so the last one is all of them"
    assert len(listings) == 319


def test_a_listing_that_is_only_a_prefix_is_refused(event_loop):
    """The jump has to land past the end. A response that still offers more is a prefix of
    the category, and everything past it would be read as gone."""
    truncated = LISTING.replace("</body>", '<a id="nextAnchor" rel="next"></a></body>')
    with pytest.raises(ValueError, match="outgrew the jump"):
        discover(event_loop, body=truncated)


def test_a_page_with_no_products_is_an_error(event_loop):
    with pytest.raises(ValueError, match="no products"):
        discover(event_loop, body="<html><body><h1>Smartphones</h1></body></html>")


# --- the price a shopper actually pays ---


def test_a_members_price_is_not_offered_as_the_price(event_loop):
    """51 of 319 lead with `Friends price`. Reading `data-product-price` alone would put
    599.99 against other shops' 839.99 and call this shop the cheapest."""
    got = card(discover(event_loop))
    assert got["price"] == "839.99"
    assert got["price_loyalty"] == "599.99"


def test_an_undiscounted_card_states_one_price_and_no_member_price(event_loop):
    listings = discover(event_loop)
    plain = [listing.card for listing in listings if not listing.card["price_loyalty"]]
    assert len(plain) == 268
    assert all(item["price"] for item in plain)


def test_the_stock_word_is_the_shop_s_own(event_loop):
    listings = discover(event_loop)
    words = {listing.card["availability"] for listing in listings}
    assert words == {"In stock", "On order"}


def test_the_card_carries_the_part_number_the_page_repeats(event_loop):
    assert card(discover(event_loop))["mpn"] == "SM-S931BLBDEUE"


def test_the_placeholder_brand_is_not_carried(event_loop):
    """`Vaikimisi` is Estonian for "default" and is on every card in the category."""
    listings = discover(event_loop)
    assert all("brand" not in listing.card for listing in listings)


# --- what the product page adds ---


def test_the_page_states_the_barcode_the_brand_and_the_model(event_loop):
    """No other shop here states a model outright, so this channel needs no rule to cut
    one out of a name."""
    read = product(event_loop)
    assert read["ean"] == "8806095851136"
    assert read["brand"] == "Samsung"
    assert read["model"] == "Galaxy S25"
    assert read["mpn"] == "SM-S931BLBDEUE"


def test_the_price_and_stock_come_from_the_card_not_the_page(event_loop):
    """The page's own `Offer` states 599.99 and `InStock`; both are wrong for a shopper."""
    read = product(event_loop)
    assert read["price"] == "839.99"
    assert read["availability"] == "In stock"


def test_the_specification_list_comes_over(event_loop):
    specs = product(event_loop)["specs"]
    assert specs["colour"] == "light blue"
    assert specs["manufacturer"] == "Samsung"
    assert len(specs) > 30


def test_a_page_without_the_graph_still_parses(event_loop):
    """Everything it holds is what this channel is for, but its absence is a product
    missing its barcode rather than a run that failed."""
    # The script's type is HTML-escaped in the source, so the graph itself is what is
    # taken away rather than the tag around it.
    stripped = PRODUCT.replace('"@graph"', '"@nothing"')
    read = product(event_loop, body=stripped)
    assert read["ean"] == ""
    assert read["price"] == "839.99", "the card still knows what it costs"
    assert read["mpn"] == "SM-S931BLBDEUE", "and what it is"


def test_a_snapshot_with_no_product_page_is_an_error():
    with pytest.raises(ValueError, match="no product page"):
        Euronics().parse(Snapshot(external_id="1", parts=[]))


# --- what the reader makes of it ---


def test_the_generic_layer_already_reads_nearly_all_of_it(event_loop):
    from app.features.offers.normalization import read

    fields = read(product(event_loop), source_slug="euronics-phones", shop_slug="euronics")
    assert fields["brand_raw"] == "Samsung"
    assert fields["gtin"] == "08806095851136"
    assert fields["mpn"] == "SM-S931BLBDEUE"
    assert fields["model"] == "Galaxy S25"
    assert float(fields["price"]) == 839.99
    assert fields["availability"] == "in_stock"


def test_the_shop_s_word_for_to_order_needs_a_ruleset(event_loop):
    """`In stock` maps itself; `On order` is this shop's wording and nothing knows it yet."""
    from app.features.offers.normalization import generic

    listings = discover(event_loop)
    ordered = next(
        listing.card for listing in listings if listing.card["availability"] == "On order"
    )
    assert generic.read(ordered)["availability"] == "unknown"


# --- the shop's own ruleset ---


def reading(event_loop, payload: dict | None = None):
    from app.features.offers.normalization import read
    from app.features.offers.normalization.rules import Vocabulary

    return read(
        payload or product(event_loop),
        source_slug="euronics-phones",
        shop_slug="euronics",
        category="phones",
        vocabulary=Vocabulary(
            colours={"light blue": "blue", "blue": "blue"},
            attribute_names={"colour": "color", "internal memory": "storage_mb"},
        ),
    )


def test_in_stock_needs_no_rule_and_on_order_does(event_loop):
    """261 of 319 normalise themselves; the other 58 are this shop's own wording."""
    assert reading(event_loop)["availability"] == "in_stock"

    listings = discover(event_loop)
    ordered = next(
        listing.card for listing in listings if listing.card["availability"] == "On order"
    )
    assert reading(event_loop, ordered)["availability"] == "preorder"


def test_a_word_nobody_measured_is_not_filed_as_one_of_the_two(event_loop):
    card_now = dict(card(discover(event_loop)))
    card_now["availability"] = "Sold out"
    assert reading(event_loop, card_now)["availability"] == "unknown"


def test_a_colour_phrase_resolves_through_the_registry(event_loop):
    """`light blue` got nothing out of an exact lookup, and this shop states 63 of them."""
    assert reading(event_loop)["identity"]["color"] == "blue"


def test_the_ruleset_version_says_what_was_applied(event_loop):
    # The Samsung the fixture holds also selects the brand layer, which is the point of
    # the composed version: it names every ruleset that touched the reading.
    assert reading(event_loop)["ruleset_version"] == (
        "generic-3+phones-14+euronics-shop-1+samsung-phones-2"
    )


# --- tablets: the same pages under the tablets' own leaf ---


def test_the_tablet_channel_asks_for_its_own_leaf(event_loop):
    from app.features.runs.channels.euronics import TABLETS_CHANNEL

    asked: list[str] = []
    event_loop.run_until_complete(TABLETS_CHANNEL.discover(shop(asked=asked), job()))
    assert asked and all("/en/phones/tablets/tablets?f=" in url for url in asked)
    assert TABLETS_CHANNEL.slug == "euronics-tablets"


def tablet(name: str, model: str) -> str | None:
    from app.features.offers.normalization import read

    return read(
        {"name": name, "brand": name.split()[0], "model": model},
        source_slug="euronics-tablets",
        shop_slug="euronics",
        category="tablets",
    ).get("model")


def test_a_stated_model_gets_the_series_the_shop_left_off():
    """`Tab S11 Ultra` for `Samsung Galaxy Tab S11 Ultra, …`: every other shop writes the
    series. Where the name has lost the chip, the stated model stands."""
    assert tablet("Samsung Galaxy Tab S11 Ultra, 256 GB, 5G, gray - Tablet", "Tab S11 Ultra") == (
        "Galaxy Tab S11 Ultra"
    )
    assert tablet(
        'Apple iPad Pro 11", M5 (2025), 256 GB, WiFi, glossy, space black - Tablet',
        'iPad Pro 11" M5',
    ) == ("iPad Pro M5")
