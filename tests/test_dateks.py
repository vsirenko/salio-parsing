"""dateks.lv phones, read off the shop's own pages.

Served from two real responses captured on 22.09.2026 — the first listing page and a
product page — kept compressed because they are 400 KB and 100 KB of real markup. Nothing
here reaches the network.
"""

import gzip
import pathlib

import httpx2
import pytest

from app.features.runs.channel import Part, Snapshot
from app.features.runs.channels.dateks import SITE, Dateks
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import Job, Kind

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
LISTING = gzip.decompress((FIXTURES / "dateks_listing.html.gz").read_bytes()).decode()
PRODUCT = gzip.decompress((FIXTURES / "dateks_product.html.gz").read_bytes()).decode()


def job(kind: Kind = Kind.FULL) -> Job:
    return Job(
        run_id=1,
        source_id=1,
        source_slug="dateks-phones",
        shop_slug="dateks",
        kind=kind,
        access="retail",
        decode="markup",
        base_url=SITE,
        market_codes=["LV"],
        delivers=["catalogue", "price", "availability"],
    )


def shop(body: str = LISTING, asked: list[str] | None = None) -> Fetcher:
    """The shop, serving the captured page for whatever was asked for."""

    async def serve(request: httpx2.Request) -> httpx2.Response:
        if asked is not None:
            asked.append(str(request.url))
        return httpx2.Response(200, text=body)

    return Fetcher(rate=0, client=httpx2.AsyncClient(transport=httpx2.MockTransport(serve)))


def discover(event_loop, body: str = LISTING, asked=None):
    return event_loop.run_until_complete(Dateks().discover(shop(body, asked), job()))


def product(body: str = PRODUCT) -> dict:
    url = f"{SITE}/cenas/viedtalruni/1404114-honor-600-lite-8gb-128gb-velvet-black"
    snapshot = Snapshot(
        external_id="1404114",
        url=url,
        parts=[Part(role="detail", url=url, status=200, body=body)],
    )
    return Dateks().parse(snapshot)


# --- what the listing gives ---


def test_the_listing_yields_a_card_per_product(event_loop):
    listings = discover(event_loop)
    assert len(listings) == 24, "the shop puts 24 cards on a page"
    assert all(listing.url.startswith(f"{SITE}/cenas/viedtalruni/") for listing in listings)


def test_the_walk_starts_at_page_zero_and_covers_every_page(event_loop):
    """`/pg/0` is page one. Starting at `/pg/1` drops the first 24 products and says
    nothing about it, because the shop serves page two perfectly happily."""
    asked: list[str] = []
    discover(event_loop, asked=asked)

    assert f"{SITE}/cenas/viedtalruni/pg/0" in asked
    pages = sorted(int(url.rsplit("/", 1)[-1]) for url in asked)
    # The paginator on the captured page names 31 as its highest index: 32 pages, 0 to 31.
    assert pages == list(range(32))


def test_a_card_carries_what_a_cheap_pass_needs(event_loop):
    listings = discover(event_loop)
    card = listings[0].card

    assert card["id"] == listings[0].external_id
    assert card["name"]
    # Both prices, and the one that is the price is the one with VAT.
    assert float(card["price"]) > float(card["price_ex_vat"])
    assert card["currency"] == "EUR"
    assert card["availability"] in ("Noliktavā", "Pasūtāms", "Birojā")
    assert card["mpn"], "the manufacturer code is printed on the listing"


def test_the_manufacturer_code_comes_over_without_its_label(event_loop):
    listings = discover(event_loop)
    assert all(not card.card["mpn"].startswith("Preces kods") for card in listings)


def test_a_quick_pass_reads_the_card_and_opens_nothing(event_loop):
    """What `delivers_quick` is for: 32 requests for the whole category's prices."""
    asked: list[str] = []
    listings = event_loop.run_until_complete(Dateks().discover(shop(asked=asked), job(Kind.QUICK)))

    read = Dateks().read_listing(listings[0])
    assert read["price"] and read["availability"]
    assert all("/pg/" in url for url in asked), "a cheap pass opens no product page"


def test_a_page_with_no_products_is_an_error_rather_than_an_empty_shop(event_loop):
    """The shop moved this category once already and left the old address serving 200.

    A channel that returned nothing here would be read as a shop that sold nothing, and
    what is not seen is what the run contract turns into an absence.
    """
    with pytest.raises(ValueError, match="no products"):
        discover(event_loop, body="<html><body><h1>Mobilie telefoni</h1></body></html>")


# --- what the product page adds ---


def test_the_page_gives_the_brand_the_listing_has_no_room_for():
    assert product()["brand"] == "Honor"


def test_the_price_is_the_one_with_vat():
    read = product()
    # The same number the listing prints as `323,81 €`, not the `bez PVN` one beside it.
    assert float(read["price"]) == 323.81
    assert read["currency"] == "EUR"


def test_availability_is_the_shop_s_word_and_not_the_schema_claim():
    """The page's own schema.org block says `InStock` for every product in the category,
    including the 513 of 745 the shop describes as `Pasūtāms`."""
    read = product()
    assert read["availability"] == "Noliktavā"
    assert read["quantity"] == 3
    assert "InStock" not in str(read.get("availability"))


def test_the_barcode_arrives_once_however_many_times_it_is_printed():
    """Three labels in two blocks is six lines for one number."""
    assert product()["barcodes"] == ["6936520895564"]


def test_the_barcode_is_handed_over_as_a_list_for_someone_else_to_choose():
    """A channel does not decide which of a shop's numbers is a barcode."""
    assert isinstance(product()["barcodes"], list)


def test_both_specification_blocks_come_over():
    read = product()
    assert read["specs"]["3G standarti Tīkls"] == "WCDMA"
    assert read["specs_original"]["3G standards Network"] == "WCDMA"


def test_a_specification_name_keeps_its_group():
    """`Displejs - Displeja diagonāle - 16,8 cm (6,6")` splits at the last separator.

    Splitting at the first files every display row under `Displejs`, where each one
    overwrites the last.
    """
    specs = product()["specs"]
    assert specs["Displejs - Displeja diagonāle"] == '16,8 cm (6,6")'
    assert specs["Displejs - Displeja izšķirtspēja"] == "1200 x 2600 pikseļi"


def test_the_shop_s_own_id_is_not_offered_as_a_part_number():
    """`sku` in the page's schema.org block is this shop's counter, and the generic reader
    takes a `sku` for a manufacturer's part number."""
    read = product()
    assert read["id"] == "1404114"
    assert read["mpn"] == "5109CJCV"
    assert "sku" not in read


def test_a_page_without_the_schema_block_still_parses():
    """Everything it gives has a duller source, so its absence is a missing brand."""
    stripped = PRODUCT.replace('type="application/ld+json"', 'type="text/plain"')
    read = product(stripped)
    assert read["brand"] == ""
    assert read["mpn"] == "5109CJCV", "the label under the cart button still has it"
    assert read["availability"] == "Noliktavā"


def test_a_snapshot_with_no_product_page_is_an_error():
    with pytest.raises(ValueError, match="no product page"):
        Dateks().parse(Snapshot(external_id="1", parts=[]))


# --- what the reader makes of it ---


def test_the_generic_layer_already_reads_most_of_it():
    from app.features.offers.normalization import read

    fields = read(product(), source_slug="dateks-phones", shop_slug="dateks")
    assert fields["title"] == "Honor 600 Lite, 8GB/128GB, Velvet Black"
    assert fields["brand_raw"] == "Honor"
    assert fields["mpn"] == "5109CJCV"
    assert float(fields["price"]) == 323.81
    assert fields["currency_code"] == "EUR"


def test_generic_alone_does_not_know_where_the_barcode_is():
    """`barcodes` is this shop's own key, so the layer above has to pick out of the list.

    Reading the list generically would be worse than not reading it: `_gtin` joins every
    digit it finds, so two codes would become one 26-digit number.
    """
    from app.features.offers.normalization import generic

    assert generic.read(product())["gtin"] is None


# --- the shop's own ruleset ---


def reading(payload: dict | None = None):
    from app.features.offers.normalization import read
    from app.features.offers.normalization.rules import Vocabulary

    colours = {
        "velvet black": "black",
        "black": "black",
        "orange": "orange",
        "black-orange": "black-orange",
        "yellow": "yellow",
    }
    return read(
        payload or product(),
        source_slug="dateks-phones",
        shop_slug="dateks",
        category="phones",
        vocabulary=Vocabulary(colours=colours),
    )


def test_the_barcode_is_picked_out_of_the_list():
    """643 of 745 name at least one code, and 99 name more than one — the maker's beside a
    distributor's. Dropping those would give up 88 barcodes another shop also has."""
    assert reading()["gtin"] == "06936520895564"


def test_a_card_naming_no_code_reads_as_having_none():
    payload = product() | {"barcodes": []}
    assert reading(payload)["gtin"] is None


def test_the_shop_s_word_decides_what_is_in_stock():
    """`InStock` in the page's own markup is true of all 745 and of 221 of them in fact."""
    assert reading()["availability"] == "in_stock"
    assert reading(product() | {"availability": "Pasūtāms"})["availability"] == "preorder"
    assert reading(product() | {"availability": "Birojā"})["availability"] == "in_stock"
    # A word nobody has measured is not quietly filed as one of the two known ones.
    assert reading(product() | {"availability": "Nav pieejams"})["availability"] == "unknown"


def test_the_model_is_the_name_in_front_of_the_first_comma():
    """`Honor 600 Lite, 8GB/128GB, Velvet Black` — the brand off the front, the comma the cut."""
    assert reading()["model"] == "600 Lite"


def test_a_name_with_no_comma_is_cut_at_the_capacity():
    """A supplier's description pasted whole. Without this the capacity travels as part of
    the model and files one phone as one product per capacity."""
    payload = product() | {
        "title": "Samsung S26 Ultra 5G EE 256GB Black Android",
        "name": "Samsung S26 Ultra 5G EE 256GB Black Android",
        "brand": "Samsung",
    }
    assert reading(payload)["model"] == "S26 Ultra 5G EE"


def test_the_working_memory_is_not_left_on_the_model():
    payload = product() | {"name": "Wave MOBILE PHONE WAVE 10C/4/128GB BLACK", "brand": "Wave"}
    assert reading(payload)["model"] == "MOBILE PHONE WAVE 10C"


def test_the_colour_is_the_last_segment_of_the_name():
    assert reading()["identity"]["color"] == "black"


def test_the_shop_s_notes_after_the_colour_are_stepped_over():
    """`…, Yellow, No Charger` — the colour is still the last segment that is one."""
    payload = product() | {"name": "Blackview BV7300, 6GB/256GB, Yellow, No Charger"}
    assert reading(payload)["identity"]["color"] == "yellow"


def test_a_two_tone_case_is_its_own_colour():
    payload = product() | {"name": "Ulefone Armor X32, 6GB/128GB, Black/Orange"}
    assert reading(payload)["identity"]["color"] == "black-orange"


def test_a_marketing_name_resolves_to_nothing():
    """`PANTONE Titan`, `Awesome Charcoal`, `Starlight` — 20 of 745 and left visible."""
    payload = product() | {
        "title": "Motorola Edge 70 Pro, 8GB/256GB, PANTONE Titan",
        "name": "Motorola Edge 70 Pro, 8GB/256GB, PANTONE Titan",
        # Without this the category's rules find `Velvet Black` in the table and the name
        # is never consulted — which is the right order, and not what is under test here.
        "specs": {},
        "specs_original": {},
    }
    assert "color" not in reading(payload)["identity"]


def test_without_the_registry_the_gap_stays_visible():
    from app.features.offers.normalization import read

    fields = read(product(), source_slug="dateks-phones", shop_slug="dateks", category="phones")
    assert "color" not in fields["identity"]


def test_the_ruleset_version_says_what_was_applied():
    assert reading()["ruleset_version"] == "generic-2+phones-12+dateks-shop-1+dateks-4"
