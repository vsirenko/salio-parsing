"""discover.lv phones, read out of the shop's own export.

Served from the real `/catalog.xml` captured on 22.09.2026 — its phone section whole, and
five records from other sections so the filter has something to filter. Nothing here
reaches the network.
"""

import gzip
import pathlib

import httpx2
import pytest

from app.features.runs.channel import Snapshot
from app.features.runs.channels.discover import FEED, Discover
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import Job, Kind

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
CATALOG = gzip.decompress((FIXTURES / "discover_catalog.xml.gz").read_bytes()).decode()


def job() -> Job:
    return Job(
        run_id=1,
        source_id=1,
        source_slug="discover-phones",
        shop_slug="discover",
        kind=Kind.FULL,
        access="wholesale",
        decode="xml",
        base_url="https://www.discover.lv",
        market_codes=["LV"],
        delivers=["catalogue", "price", "availability"],
    )


def shop(body: str = CATALOG, asked: list[str] | None = None) -> Fetcher:
    async def serve(request: httpx2.Request) -> httpx2.Response:
        if asked is not None:
            asked.append(str(request.url))
        return httpx2.Response(200, text=body)

    return Fetcher(rate=0, client=httpx2.AsyncClient(transport=httpx2.MockTransport(serve)))


def discover(event_loop, body: str = CATALOG, asked=None):
    return event_loop.run_until_complete(Discover().discover(shop(body, asked), job()))


def one(listings, name_contains: str) -> dict:
    return next(x.card for x in listings if name_contains in x.card["name"])


# --- one request is the whole shop ---


def test_the_whole_shop_arrives_in_one_request(event_loop):
    asked: list[str] = []
    listings = discover(event_loop, asked=asked)

    assert asked == [FEED]
    assert len(listings) == 560


def test_only_the_phone_section_is_taken(event_loop):
    """The export is the whole shop — fishing rods and stoves included."""
    listings = discover(event_loop)
    assert all(x.card["category"].startswith("Mobilie telefoni") for x in listings)


def test_a_section_that_is_no_longer_there_is_an_error(event_loop):
    """An export that answers and holds no phones is a section that was renamed, not a shop
    that sold out — and reporting none would licence an absence."""
    with pytest.raises(ValueError, match="no products"):
        discover(event_loop, body="<root></root>")


def test_nothing_is_fetched_per_product(event_loop):
    listings = discover(event_loop)
    snapshot = event_loop.run_until_complete(Discover().fetch(None, listings[0]))
    assert Discover().parse(snapshot)["id"] == listings[0].external_id


def test_a_snapshot_with_no_record_is_an_error():
    with pytest.raises(ValueError, match="no export record"):
        Discover().parse(Snapshot(external_id="1", parts=[]))


# --- what a record carries ---


def test_the_shop_s_own_number_is_the_last_part_of_the_link(event_loop):
    card = one(discover(event_loop), "iPhone 16 128GB Black")
    assert card["id"] == "57874"
    assert card["url"].endswith("/57874")


def test_the_html_the_shop_exported_by_accident_comes_off(event_loop):
    """One section arrives as `Mobilie telefoni >> <b>Apple`, a bold tag that leaked out of
    the shop's page. Carried as it stands it is a brand nobody can resolve."""
    listings = discover(event_loop)
    brands = {x.card["brand"] for x in listings}
    assert "Apple" in brands
    assert not any("<" in brand for brand in brands)


def test_the_family_designation_is_kept_apart_from_the_name(event_loop):
    """`(SM-S948B)` covers every colour and capacity of that phone."""
    listings = discover(event_loop)
    lines = {x.card["line"] for x in listings if x.card["line"]}
    assert any(line.startswith("SM-") for line in lines)


def test_the_stock_flag_is_carried_as_the_shop_wrote_it(event_loop):
    listings = discover(event_loop)
    assert {x.card["in_stock"] for x in listings} == {"1"}


# --- the shop's own ruleset ---


def reading(event_loop, name_contains: str = "iPhone 16 128GB Black"):
    from app.features.offers.normalization import read
    from app.features.offers.normalization.rules import Vocabulary

    return read(
        one(discover(event_loop), name_contains),
        source_slug="discover-phones",
        shop_slug="discover",
        category="phones",
        vocabulary=Vocabulary(colours={"black": "black", "titanium silver": "silver"}),
    )


def test_the_flag_the_table_does_not_know_is_read_here(event_loop):
    """Generic's table knows `true` and `yes`, not `1`, so all 560 arrived `unknown`."""
    assert reading(event_loop)["availability"] == "in_stock"


def test_the_model_is_the_name_in_front_of_the_first_capacity(event_loop):
    fields = reading(event_loop)
    assert fields["model"] == "iPhone 16"
    assert fields["brand_raw"] == "Apple"


def test_the_family_designation_is_not_part_of_the_model(event_loop):
    """222 names carry it in the middle of them — `Galaxy S26 Ultra (SM-S948B) Titanium`."""
    listings = discover(event_loop)
    with_line = next(x.card for x in listings if x.card["line"])
    from app.features.offers.normalization import read

    fields = read(with_line, source_slug="discover-phones", shop_slug="discover", category="phones")
    assert with_line["line"] not in (fields["model"] or "")
    assert fields["model"]


def test_a_bracket_that_is_not_the_family_stays(event_loop):
    """Taking out any bracket cost `Apple iPhone SE (2022)` its year, which on an iPhone SE
    is not decoration but which one it is."""
    from app.features.offers.normalization import read

    card = dict(one(discover(event_loop), "iPhone"))
    card |= {"name": "Apple iPhone SE (2022) 5G 64GB Midnight", "brand": "Apple", "line": ""}
    assert read(card, source_slug="discover-phones", shop_slug="discover", category="phones")[
        "model"
    ] == ("iPhone SE (2022) 5G")


def test_the_working_memory_does_not_travel_with_the_model(event_loop):
    """217 of the 560 write `12/128GB`, with a unit only on the second half. Cutting at the
    unit leaves `12/` behind, and `Pixel 10` becomes one entry per memory size."""
    from app.features.offers.normalization import read

    card = dict(one(discover(event_loop), "iPhone"))
    card |= {"name": "Google Pixel 10 12/128GB Frost", "brand": "Google", "line": ""}
    assert (
        read(card, source_slug="discover-phones", shop_slug="discover", category="phones")["model"]
        == "Pixel 10"
    )


def test_there_is_no_barcode_and_no_part_number(event_loop):
    """Not in the export and not on the page. Everything rests on brand, model and axes."""
    fields = reading(event_loop)
    assert fields["gtin"] is None
    assert fields["mpn"] is None


def test_the_colour_is_what_follows_the_capacity(event_loop):
    assert reading(event_loop)["identity"]["color"] == "black"


def test_the_ruleset_version_says_what_was_applied(event_loop):
    assert reading(event_loop)["ruleset_version"].startswith(
        "generic-3+phones-13+discover-shop-1+discover-6"
    )


# --- tablets: two sections that share their shelves ---


def test_the_tablets_are_picked_out_of_the_sections_they_share():
    from app.features.runs.channels.discover import APPLE_SECTION, MIXED_SECTION, a_tablet

    assert a_tablet(MIXED_SECTION, "Samsung Galaxy Tab S10 FE WiFi 10.9 128GB Gray (SM-X520)")
    assert not a_tablet(MIXED_SECTION, "Microsoft Surface Laptop 13.5 16GB/512GB/Intel i7")
    assert a_tablet(APPLE_SECTION, "Apple iPad Air 11 M3 (2025) 128GB Cellular Blue (MCFW4)")
    assert not a_tablet(APPLE_SECTION, "Apple MacBook Neo 13 A18 Pro 8GB/256GB 6C Silver")
    assert not a_tablet("Mobilie telefoni >> Apple", "Apple iPhone 17 256GB Black")


def test_the_laptops_are_the_macbooks_and_the_one_laptop_beside_the_tablets():
    from app.features.runs.channels.discover import APPLE_SECTION, MIXED_SECTION, a_laptop

    assert a_laptop(APPLE_SECTION, "Apple MacBook Air 13 M5 13.6 16GB/1TB 10C EN ENG Midnight")
    assert a_laptop(MIXED_SECTION, "Microsoft Surface Laptop 13.5 16GB/512GB/Intel i7")
    assert not a_laptop(MIXED_SECTION, "Samsung Galaxy Tab S10 FE WiFi 10.9 128GB Gray")
    assert not a_laptop(APPLE_SECTION, "Apple Mac mini (2024) M4 10C 16GB/512GB (MU9E3)")
    assert not a_laptop("Mobilie telefoni >> Apple", "Apple MacBook Air 13 M5 16GB/512GB")


def tablet(name: str, brand: str = "", line: str = "") -> dict:
    from app.features.offers.normalization import read
    from app.features.offers.normalization.rules import Vocabulary

    return read(
        {"id": "1", "name": name, "brand": brand, "line": line},
        source_slug="discover-tablets",
        shop_slug="discover",
        category="tablets",
        vocabulary=Vocabulary(
            category_names=frozenset({"planšetdators"}),
            brand_names=frozenset({"samsung", "xiaomi", "apple"}),
        ),
    )


def test_a_tablet_s_maker_screen_and_model_come_out_of_its_name():
    """The section names no maker, and the screen is a bare number in the name."""
    fields = tablet("Samsung X230 Galaxy Tab A11+ 11 128GB Gray (Grey)")
    assert fields["brand_raw"] == "Samsung"
    assert fields["model"] == "Galaxy Tab A11+"
    assert fields["identity"]["screen_inch"] == 11
    # Two numbers: the first is the model's, the last the screen.
    pad = tablet("Xiaomi Pad 8 Pro 11 8/256GB Gray (Grey)")
    assert (pad["model"], pad["identity"]["screen_inch"]) == ("Pad 8 Pro", 11)
    # The screen inside the name, and the word for the category before the maker.
    air = tablet("Planšetdators Apple iPad Air 13 M3 (2025) 128GB Space Gray", brand="Apple")
    assert air["model"] == "iPad Air M3 (2025)"
    assert air["identity"]["screen_inch"] == 13


def test_an_ipad_naming_no_radio_is_the_wifi_one():
    """27 of 27 such iPads are Wi-Fi at the other shops that list their part number."""
    assert tablet("Apple iPad Air 11 M4 (2026) 128GB Blue (MH314)", "Apple")["identity"][
        "connectivity"
    ] == ("wifi")
    assert tablet("Apple iPad Air 13 M3 (2025) 256GB + Cellular Blue (MCJ74)", "Apple")["identity"][
        "connectivity"
    ] == ("cellular")
    # Not checked for any other maker, so not read.
    assert "connectivity" not in tablet("Samsung Galaxy Tab A11 8.7 64GB Gray (Grey)")["identity"]


def test_a_samsung_code_names_the_radio_the_name_leaves_out():
    """Code ending 0 read Wi-Fi 133 times and 5 or 6 cellular 165, across every shop."""
    wifi = tablet("Samsung X230 Galaxy Tab A11+ 11 128GB Gray (Grey)")
    assert wifi["identity"]["connectivity"] == "wifi"
    lte = tablet("Samsung X135 Galaxy Tab A11 8.7 64GB Gray (Grey)")
    assert lte["identity"]["connectivity"] == "cellular"
    # A name and a code naming different radios: neither is taken.
    both = tablet("Samsung Galaxy Tab Active5 Pro WiFi 10.1 128GB Green (SM-X356)", line="SM-X356")
    assert "connectivity" not in both["identity"]
    # A resolution is not a code.
    assert "connectivity" not in tablet("Samsung Galaxy Tab 11 2560x1600 128GB Gray")["identity"]


def test_a_whole_part_number_in_the_bracket_is_a_part_number():
    """13 of 222 brackets were whole part numbers, 9 of them another shop's too."""
    whole = tablet(
        'Samsung Galaxy Tab S11 Ultra 14.6" 256GB SM-X930 Grey (SM-X930NZAREUE)',
        line="SM-X930NZAREUE",
    )
    assert whole["mpn"] == "SM-X930NZAREUE"
    assert whole["identity"]["connectivity"] == "wifi"
    family = tablet("Samsung Galaxy Tab S10 FE 10.9 128GB Gray (SM-X520)", line="SM-X520")
    assert not family.get("mpn")


def test_a_screen_protector_is_not_a_tablet_even_on_a_reparse():
    """The word `iPad` let one in; a tablet names its capacity and it did not."""
    import json as _json

    from app.features.runs.channel import Part
    from app.features.runs.channels.discover import APPLE_SECTION, TABLETS_CHANNEL, a_tablet

    name = "Aizsargstikls for Apple Ipad gen 7,8,9 (10.2”/10.5”) SCREENOR 9H screen protector"
    assert not a_tablet(APPLE_SECTION, name)
    record = {"id": "1", "name": name, "category": APPLE_SECTION, "line": ""}
    snapshot = Snapshot(
        external_id="1",
        parts=[Part(role="feed", url=FEED, status=200, body=_json.dumps(record))],
    )
    with pytest.raises(ValueError, match="not one of"):
        TABLETS_CHANNEL.parse(snapshot)
