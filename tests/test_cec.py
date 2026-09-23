"""shop.cec.lv phones, read through the shop's own GraphQL.

Served from two real responses captured on 22.09.2026 — the category lookup and the whole
`iPhone` category with its variants. Nothing here reaches the network.
"""

import gzip
import json
import pathlib

import httpx2
import pytest

from app.features.runs.channel import Snapshot
from app.features.runs.channels.cec import SITE, Cec
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import Job, Kind

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
ROUTE = (FIXTURES / "cec_route.json").read_text()
PRODUCTS = gzip.decompress((FIXTURES / "cec_phones.json.gz").read_bytes()).decode()


def job() -> Job:
    return Job(
        run_id=1,
        source_id=1,
        source_slug="cec-phones",
        shop_slug="cec",
        kind=Kind.FULL,
        access="wholesale",
        decode="graphql",
        base_url=SITE,
        market_codes=["LV"],
        delivers=["catalogue", "price", "availability"],
    )


def shop(route: str = ROUTE, products: str = PRODUCTS, asked: list[dict] | None = None):
    """The shop, answering the category lookup and then the product query."""

    async def serve(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        if asked is not None:
            asked.append(body)
        return httpx2.Response(200, text=route if "route" in body["query"] else products)

    return Fetcher(rate=0, client=httpx2.AsyncClient(transport=httpx2.MockTransport(serve)))


def discover(event_loop, **kwargs):
    return event_loop.run_until_complete(Cec().discover(shop(**kwargs), job()))


def one(listings, sku: str):
    return next(listing.card for listing in listings if listing.external_id == sku)


# --- the variants are the offers ---


def test_every_buyable_phone_is_its_own_listing(event_loop):
    """All twelve items in the category are configurable. Reading them instead of their
    variants would file a whole family as one product."""
    listings = discover(event_loop)
    assert len(listings) == 92
    assert all(listing.external_id for listing in listings)


def test_a_variant_carries_apple_s_own_code(event_loop):
    """89 of these 92 are already in this system, published by up to four other shops."""
    card = one(discover(event_loop), "MK2D4HX/A")
    assert card["mpn"] == "MK2D4HX/A"
    assert card["id"] == card["mpn"]


def test_the_family_name_is_the_model(event_loop):
    """Stated rather than cut out of anything: the configurable is the family."""
    card = one(discover(event_loop), "MK2D4HX/A")
    assert card["model"] == "iPhone Duo"
    assert card["name"] == "iPhone Duo 256GB Star White"


def test_the_option_values_come_over_as_the_shop_labels_them(event_loop):
    card = one(discover(event_loop), "MK2D4HX/A")
    assert card["attributes"]["color"] == "Star White"
    assert card["attributes"]["erply_storage"] == "256GB"


def test_the_price_loses_the_double_s_tail(event_loop):
    """`2389.000043` is Magento's float, not the shop's price."""
    assert one(discover(event_loop), "MK2D4HX/A")["price"] == "2389.00"


def test_the_category_is_looked_up_by_path(event_loop):
    """The uid is a base64 of an internal number that a catalogue rebuild can change."""
    asked: list[dict] = []
    discover(event_loop, asked=asked)

    assert "route" in asked[0]["query"]
    assert asked[0]["variables"]["url"] == "iphone"
    assert asked[1]["variables"]["uid"] == json.loads(ROUTE)["data"]["route"]["uid"]


def test_a_missing_category_is_an_error(event_loop):
    with pytest.raises(ValueError, match="no category"):
        discover(event_loop, route=json.dumps({"data": {"route": None}}))


def test_a_graphql_error_is_a_failure_and_not_an_empty_category(event_loop):
    """The endpoint answers 200 and puts the failure in the body."""
    broken = json.dumps({"errors": [{"message": "Cannot query field variants"}]})
    with pytest.raises(ValueError, match="graphql"):
        discover(event_loop, products=broken)


def test_nothing_is_fetched_per_product(event_loop):
    listings = discover(event_loop)
    snapshot = event_loop.run_until_complete(Cec().fetch(None, listings[0]))
    assert Cec().parse(snapshot)["mpn"] == listings[0].external_id


def test_a_snapshot_with_no_record_is_an_error():
    with pytest.raises(ValueError, match="no product record"):
        Cec().parse(Snapshot(external_id="1", parts=[]))


# --- what the reader makes of it ---


def reading(event_loop, sku: str = "MK2D4HX/A"):
    from app.features.offers.normalization import read
    from app.features.offers.normalization.rules import Vocabulary

    return read(
        one(discover(event_loop), sku),
        source_slug="cec-phones",
        shop_slug="cec",
        category="phones",
        vocabulary=Vocabulary(
            colours={"star white": "white"},
            attribute_names={"color": "color", "erply_storage": "storage_mb"},
        ),
    )


def test_the_brand_is_supplied_because_the_shop_states_none(event_loop):
    """41 fields on a product and not one of them is a maker."""
    fields = reading(event_loop)
    assert fields["brand_raw"] == "Apple"


def test_the_brand_is_tied_to_the_category_and_not_to_the_channel(event_loop):
    """The shop also sells Bose, Sonos and Bang & Olufsen."""
    from app.features.offers.normalization import read

    card = dict(one(discover(event_loop), "MK2D4HX/A"))
    card["category"] = "Speakers"
    assert (
        read(card, source_slug="cec-phones", shop_slug="cec", category="phones")["brand_raw"]
        is None
    )


def test_the_part_number_and_the_model_need_no_rule(event_loop):
    fields = reading(event_loop)
    assert fields["mpn"] == "MK2D4HX/A"
    assert fields["model"] == "iPhone Duo"
    assert float(fields["price"]) == 2389.00
    assert fields["availability"] == "in_stock"


def test_there_is_no_barcode_and_that_is_the_shop(event_loop):
    """The schema has no field for one, so this shop rests entirely on the Apple code."""
    assert reading(event_loop)["gtin"] is None


def test_the_identity_axes_come_from_the_options(event_loop):
    identity = reading(event_loop)["identity"]
    assert identity["storage_mb"] == 262144
    assert identity["color"] == "white"


def test_the_ruleset_version_says_what_was_applied(event_loop):
    assert reading(event_loop)["ruleset_version"].startswith("generic-2+phones-13+cec-1")
