"""bm.market phones, read through the shop's own GraphQL.

Served from one real response captured on 22.09.2026 — the first page of 200 products,
kept compressed because it is half a megabyte of real records. Nothing here reaches the
network.
"""

import gzip
import json
import pathlib

import httpx2
import pytest

from app.features.runs.channel import Snapshot
from app.features.runs.channels.bm import SITE, Bm, fields_of
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import Job, Kind

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
PAGE = gzip.decompress((FIXTURES / "bm_phones.json.gz").read_bytes()).decode()
ITEMS = json.loads(PAGE)["data"]["products"]["items"]


def job() -> Job:
    return Job(
        run_id=1,
        source_id=1,
        source_slug="bm-phones",
        shop_slug="bm",
        kind=Kind.FULL,
        access="wholesale",
        decode="graphql",
        base_url=SITE,
        market_codes=["LV"],
        delivers=["catalogue", "price", "availability"],
    )


def shop(body: str = PAGE, asked: list[dict] | None = None) -> Fetcher:
    """The shop, answering every page with the captured one.

    `total_count` in it is 937 against 200 items, so `discover` stops on the count rather
    than on an empty page — which is the loop that matters.
    """

    async def serve(request: httpx2.Request) -> httpx2.Response:
        if asked is not None:
            asked.append(json.loads(request.content))
        return httpx2.Response(200, text=body)

    return Fetcher(rate=0, client=httpx2.AsyncClient(transport=httpx2.MockTransport(serve)))


def discover(event_loop, body: str = PAGE, asked=None):
    return event_loop.run_until_complete(Bm().discover(shop(body, asked), job()))


def one(name_contains: str) -> dict:
    return next(fields_of(i) for i in ITEMS if name_contains in i["name"])


# --- what the endpoint gives ---


def test_a_page_yields_a_listing_per_product(event_loop):
    listings = discover(event_loop)
    assert len(listings) >= 200
    assert all(listing.external_id for listing in listings)
    assert all(listing.url.startswith(f"{SITE}/") for listing in listings)


def test_the_walk_asks_for_the_phones_leaf_and_pages_through_it(event_loop):
    """`Mobilie telefoni` is the bigger of the two categories and holds Apple Watches."""
    asked: list[dict] = []
    discover(event_loop, asked=asked)

    assert all(body["variables"]["uid"] == "MTIy" for body in asked)
    assert [body["variables"]["page"] for body in asked] == list(range(1, len(asked) + 1))


def test_a_graphql_error_is_a_failure_and_not_an_empty_category(event_loop):
    """The endpoint answers 200 and puts the failure in the body, so a query that broke
    looks from the outside exactly like a shop that sold out."""
    broken = json.dumps({"errors": [{"message": "Cannot query field sku on Product"}]})
    with pytest.raises(ValueError, match="graphql"):
        discover(event_loop, body=broken)


def test_nothing_is_fetched_per_product(event_loop):
    """A wholesale channel: the record from the listing is the whole record."""
    listings = discover(event_loop)
    snapshot = event_loop.run_until_complete(Bm().fetch(None, listings[0]))
    assert snapshot.part("graphql") is not None
    assert Bm().parse(snapshot)["id"] == listings[0].external_id


def test_a_snapshot_with_no_record_is_an_error():
    with pytest.raises(ValueError, match="no product record"):
        Bm().parse(Snapshot(external_id="1", parts=[]))


# --- what a record carries ---


def test_the_brand_comes_out_of_the_selected_options():
    """`manufacturer` is a Magento select, so its `value` is null and the label is
    elsewhere. Asking only for the value loses the brand on all 937 and looks like it
    worked, because the attribute is there and merely empty."""
    assert one("Xiaomi 15T")["brand"] == "Xiaomi"


def test_the_price_and_the_barcode_are_the_shop_s_own():
    read = one("Xiaomi 15T")
    assert read["ean"] == "6932554448912"
    assert read["currency"] == "EUR"
    assert float(read["price"]) > 0


def test_availability_is_the_word_beside_the_stock_flag_and_not_the_flag():
    """`stock_status` reads `IN_STOCK` on 936 of 937 — Magento saying the shop will sell
    it. `availability_type` says 934 of them are to order."""
    read = one("Xiaomi 15T")
    assert read["availability"] == "Pēc pasūtījuma"
    assert read["stock_status"] == "IN_STOCK"


def test_the_shop_s_own_number_is_not_offered_as_a_part_number():
    read = one("Xiaomi 15T")
    assert read["id"] == "1482480"
    assert "sku" not in read


def test_magento_s_own_bookkeeping_is_not_carried_as_a_specification():
    """`visibility`, `tax_class_id` and a thumbnail are on every product and describe
    none of them; a reader looking for a specification should not have to step over them."""
    attributes = one("Xiaomi 15T")["attributes"]
    assert not {"visibility", "status", "thumbnail", "tier_price", "url_key"} & set(attributes)


def test_the_specification_codes_keep_the_names_the_shop_gave_them():
    """`bm_operativa_atmina_545` is the working memory and nothing in the record says so —
    an invented name here would be our vocabulary wearing theirs."""
    enriched = next(fields_of(i) for i in ITEMS if "bm_operativa_atmina_545" in json.dumps(i))
    assert "bm_operativa_atmina_545" in enriched["attributes"]


def test_half_the_catalogue_carries_no_attributes_at_all():
    """476 of 937 have the attribute block and the rest have a name and a price. It is the
    shop's split, not a parsing failure, and the reading has to survive it."""
    read = [fields_of(i) for i in ITEMS]
    bare = [r for r in read if not r["ean"] and not r["mpn"]]
    assert bare, "the captured page holds some of both"
    assert all(r["name"] and r["price"] for r in bare)


def test_the_generic_layer_already_reads_most_of_it():
    from app.features.offers.normalization import read

    fields = read(one("Xiaomi 15T"), source_slug="bm-phones", shop_slug="bm")
    assert fields["brand_raw"] == "Xiaomi"
    assert fields["gtin"] == "06932554448912"
    assert fields["mpn"] == "MZB0KY9EU"
    assert fields["currency_code"] == "EUR"


# --- the shop's own ruleset ---


def reading(payload: dict | None = None):
    from app.features.offers.normalization import read
    from app.features.offers.normalization.rules import Vocabulary

    palette = {
        "grey": "gray",
        "gray": "gray",
        "silver": "silver",
        "matte charcoal": "charcoal",
        "cosmic orange": "orange",
    }
    return read(
        payload or one("Xiaomi 15T"),
        source_slug="bm-phones",
        shop_slug="bm",
        category="phones",
        vocabulary=Vocabulary(colours=palette),
    )


def test_the_shop_s_word_decides_what_is_in_stock():
    """934 of 937 are to order. `stock_status` calls all of them `IN_STOCK`."""
    assert reading()["availability"] == "preorder"
    assert reading(one("Xiaomi 15T") | {"availability": "Ir veikalā"})["availability"] == "in_stock"
    # A word nobody has measured is not quietly filed as one of the two known ones.
    assert reading(one("Xiaomi 15T") | {"availability": "Nav"})["availability"] == "unknown"


def test_the_model_is_the_name_in_front_of_the_first_capacity():
    """`Xiaomi 15T 5G Dual Sim 12GB RAM 256GB - Grey` — the brand off, the capacity the cut."""
    assert reading()["model"] == "15T 5G Dual Sim"


def test_the_model_survives_a_name_with_no_separator_before_the_colour():
    payload = one("Xiaomi 15T") | {"name": "Apple iPhone 18 Pro Max 2TB Silver", "brand": "Apple"}
    assert reading(payload)["model"] == "iPhone 18 Pro Max"


def test_apple_s_code_is_read_out_of_the_name_when_the_field_is_empty():
    """The shop writes it in one place or the other and never both: 120 of the 155 Apple
    products with no `mpn` have it at the end of the name."""
    payload = one("Xiaomi 15T") | {
        "name": "Apple iPhone 17 Pro 512GB Cosmic Orange MG8M4",
        "brand": "Apple",
        "mpn": "",
    }
    assert reading(payload)["mpn"] == "MG8M4"


def test_a_part_number_the_shop_states_is_not_overwritten():
    payload = one("Xiaomi 15T") | {
        "name": "Apple iPhone 17 Pro 512GB Cosmic Orange MG8M4",
        "brand": "Apple",
        "mpn": "MG8M4ZD/A",
    }
    assert reading(payload)["mpn"] == "MG8M4ZD/A"


def test_the_code_is_read_for_apple_only():
    """Over the other 741 products the same pattern matched twice and was the model both
    times."""
    payload = one("Xiaomi 15T") | {"name": "Emporia FN313", "brand": "Emporia", "mpn": ""}
    assert reading(payload)["mpn"] is None


def test_the_colour_is_what_follows_the_last_capacity():
    """The last, because the working memory is written the same way: `8GB 128GB Charcoal`."""
    payload = one("Xiaomi 15T") | {
        "name": "Motorola XT2333-3 8GB 128GB Matte Charcoal",
        "brand": "Motorola",
        "color": "",
        "attributes": {},
    }
    assert reading(payload)["identity"]["color"] == "charcoal"


def test_apples_code_does_not_hide_the_colour():
    payload = one("Xiaomi 15T") | {
        "name": "Apple iPhone 17 Pro 512GB Cosmic Orange MG8M4",
        "brand": "Apple",
        "color": "",
        "attributes": {},
    }
    assert reading(payload)["identity"]["color"] == "orange"


def test_a_marketing_name_resolves_to_nothing():
    """`Fog`, `Canyon`, `Lavander` — registry gaps, left visible."""
    payload = one("Xiaomi 15T") | {
        "name": "Nothing Phone 3a 256GB Canyon",
        "brand": "Nothing",
        "color": "",
        "attributes": {},
    }
    assert "color" not in reading(payload)["identity"]


def test_the_ruleset_version_says_what_was_applied():
    assert reading()["ruleset_version"] == "generic-2+phones-12+bm-shop-1+bm-3"
