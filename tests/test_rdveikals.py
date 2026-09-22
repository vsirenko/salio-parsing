"""rdveikals.lv phones, read off the shop's own pages.

Served from two real responses captured on 22.09.2026 — a listing page and a product page,
kept compressed because they are 860 KB and 400 KB of real markup. Nothing here reaches the
network.
"""

import gzip
import pathlib
import re

import httpx2
import pytest

from app.features.offers.normalization import read
from app.features.runs.channel import Part, Snapshot
from app.features.runs.channels.rdveikals import SITE, Rdveikals
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import Job, Kind

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
LISTING = gzip.decompress((FIXTURES / "rdveikals_listing.html.gz").read_bytes()).decode()
PRODUCT = gzip.decompress((FIXTURES / "rdveikals_product.html.gz").read_bytes()).decode()


def job(kind: Kind = Kind.FULL) -> Job:
    return Job(
        run_id=1,
        source_id=1,
        source_slug="rdveikals-phones",
        kind=kind,
        access="retail",
        decode="markup",
        base_url=SITE,
        market_codes=["LV"],
        delivers=["catalogue", "price", "availability"],
    )


def shop(pages: int = 1, asked: list[str] | None = None) -> Fetcher:
    """The shop, serving the captured listing page for however many pages were asked for."""

    async def serve(request: httpx2.Request) -> httpx2.Response:
        if asked is not None:
            asked.append(str(request.url))
        return httpx2.Response(200, text=LISTING)

    return Fetcher(rate=0, client=httpx2.AsyncClient(transport=httpx2.MockTransport(serve)))


def discover(event_loop, asked=None):
    return event_loop.run_until_complete(Rdveikals().discover(shop(asked=asked), job()))


# --- what the listing gives ---


def test_the_listing_yields_a_card_per_product(event_loop):
    listings = discover(event_loop)
    assert len(listings) == 18, "the shop puts 18 cards on a page"
    assert all(item.url.startswith(SITE) for item in listings)


def test_a_card_carries_what_a_cheap_pass_needs(event_loop):
    """Price and availability without opening a single product page."""
    card = discover(event_loop)[0].card
    assert card["price"]
    assert card["delivery_code"]
    assert card["brand"]
    assert card["currency"] == "EUR"


def test_the_walk_is_by_price_and_stops_where_the_shop_says(event_loop):
    """The default sort drifts: the same walk yields about three quarters of the category,
    differently each time. This one is `sort/6`, and the page count comes from the shop."""
    asked: list[str] = []
    discover(event_loop, asked=asked)
    assert all("/sort/6/" in url for url in asked)
    # The captured page says how many there are, so the walk is as long as the shop is.
    assert len(asked) == max(int(n) for n in re.findall(r"/page/(\d+)/", LISTING))


def test_a_quick_pass_reads_the_card_and_opens_nothing(event_loop):
    listing = discover(event_loop)[0]
    fields = Rdveikals().read_listing(listing)
    assert fields["price"] == listing.card["price"]
    assert "specs" not in fields, "a card has no specification table"


# --- what the product page gives ---


def parsed() -> dict:
    return Rdveikals().parse(
        Snapshot(
            external_id="212611",
            parts=[
                Part(
                    role="detail",
                    url=f"{SITE}/products/lv/388/212611/x.html",
                    status=200,
                    body=PRODUCT,
                )
            ],
        )
    )


def test_the_page_gives_the_barcode_the_analytics_block_does_not_have(event_loop):
    assert parsed()["ean"] == "5025232891863"


def test_the_brand_comes_out_clean(event_loop):
    """`h1 [itemprop=brand]` reads `mobilais telefons Panasonic` — the word for the category
    sits inside the element naming the maker. The analytics block has neither problem, which
    is why it is read instead of taught Latvian."""
    fields = parsed()
    assert fields["brand"] == "Panasonic"
    assert fields["name"] == "KX-TU110 Blue"
    assert "mobilais telefons" in fields["title"], "the shop's own title still says it"


def test_the_article_is_not_offered_as_a_part_number(event_loop):
    """It is the shop's own six-digit counter. Named `sku` or `article` the generic reader
    would take it for the maker's part number, and it would reach the `brand_mpn` rung as a
    code no other shop could ever agree with."""
    fields = parsed()
    assert fields["product_code"] == "553544"
    assert "sku" not in fields and "article" not in fields
    assert read(fields, source_slug="rdveikals-phones", category="phones")["mpn"] is None


def test_price_and_availability_are_the_shop_s_own_words(event_loop):
    fields = parsed()
    assert fields["price"] == 38.99
    assert fields["currency"] == "EUR"
    assert fields["availability"] == "InStock"


def test_the_specification_table_comes_over_grouped(event_loop):
    """The group stays in the key: this shop lists more than one `Krāsa`, and flattening
    them would let one silently overwrite the other."""
    specs = parsed()["specs"]
    assert len(specs) > 30
    assert specs["Kopējie parametri / Krāsa"] == "Zila"
    assert all(" / " in key for key in specs), "every row is named by its group"
    assert not any(key.endswith(":") for key in specs), "the shop's colons are not part of the name"


def test_the_colour_arrives_as_a_field_rather_than_a_guess(event_loop):
    """The reason this shop is worth the markup. Elsewhere colour has to be cut out of a
    title, which is why `phones-color` is still declared and unwritten."""
    assert "Krāsa" in " ".join(parsed()["specs"])


# --- through the reading layers ---


def test_the_generic_layer_already_reads_most_of_it(event_loop):
    """No source ruleset has been written for this shop yet, and it is still legible: the
    coverage on its first run is what says which rules it needs."""
    fields = read(parsed(), source_slug="rdveikals-phones", category="phones")
    assert fields["gtin"] == "5025232891863"
    assert fields["brand_raw"] == "Panasonic"
    assert fields["price"] is not None
    assert fields["availability"] == "in_stock"


def test_a_page_without_the_analytics_block_still_parses(event_loop):
    """Nothing in it is required. A shop that drops its analytics gives a messier brand, not
    a failed run."""
    fields = Rdveikals().parse(
        Snapshot(
            external_id="212611",
            parts=[
                Part(
                    role="detail",
                    url=f"{SITE}/products/lv/388/212611/x.html",
                    status=200,
                    body=PRODUCT.replace("view_item", "view_something_else"),
                )
            ],
        )
    )
    assert fields["ean"] == "5025232891863"
    assert fields["brand"] == ""
    assert fields["specs"]


def test_a_snapshot_with_no_product_page_is_an_error(event_loop):
    with pytest.raises(ValueError):
        Rdveikals().parse(Snapshot(external_id="1", parts=[]))


# --- reading a model out of the name ---


def read_it(fields: dict) -> dict:
    return read(fields, source_slug="rdveikals-phones", category="phones")


def named(name: str, **over) -> dict:
    return {**parsed(), "name": name, **over}


def test_the_model_is_the_name_cut_at_the_capacity(event_loop):
    """`MODEL RAM/CAPACITY COLOUR`, with the brand and the word for the category already
    off the front — so the colour falls off with the capacity and nothing has to know any
    Latvian."""
    for name, expected in (
        ("Kingkong Power 5 6/ 128GB Black", "Kingkong Power 5"),
        ("Magic V6 16/ 512GB Red", "Magic V6"),
        ("600 Smart 4/ 128GB Velvet Black", "600 Smart"),
        ("Tank X 16/ 512GB Black", "Tank X"),
        ("iPhone 18 Pro Max 1TB Desert Titanium", "iPhone 18 Pro Max"),
    ):
        assert read_it(named(name))["model"] == expected, name


def test_a_name_with_no_capacity_yields_no_model(event_loop):
    """A feature phone or a desk phone. There the colour runs into the name, so two colours
    of one handset would become two products."""
    assert read_it(named("GL695 Black"))["model"] is None


def test_the_shop_s_own_model_field_is_a_line_not_a_model(event_loop):
    """`Viedtālruņa modelis` holds `Google Pixel` for 27 different phones. Matching on it
    would make one ambiguous pile out of a whole family."""
    fields = named(
        "Pixel 11 Pro 16/ 1TB Obsidian",
        specs={"Kopējie parametri / Viedtālruņa modelis": "Google Pixel"},
    )
    full = read_it(fields)
    assert full["model"] == "Pixel 11 Pro", "the model comes from the name"
    assert "_line" not in full, "the line is working state and is not stored"


def test_the_ruleset_version_says_what_was_applied(event_loop):
    assert read_it(parsed())["ruleset_version"] == "generic-1+phones-5+rdveikals-4"


# --- stock on the pass that opens no pages ---


def test_the_cheap_pass_reads_stock_from_the_delivery_estimate(event_loop):
    """Its card never says whether the shop has the thing, only how soon it could hand it
    over. All 1394 listings were coming back `unknown`, so the channel promised availability
    and delivered none."""
    for code, expected in (
        ("15min", "in_stock"),
        ("4hour", "in_stock"),
        ("10day", "preorder"),
        ("15day", "preorder"),
    ):
        fields = read(
            {"id": "1", "delivery_code": code, "price": "9.99", "currency": "EUR"},
            source_slug="rdveikals-phones",
            category="phones",
        )
        assert fields["availability"] == expected, code


def test_the_product_page_outranks_the_estimate(event_loop):
    """A page states the answer outright. The estimate is what a cheap pass falls back on,
    not a second opinion about a page that already said."""
    fields = read(
        {**parsed(), "delivery_code": "15day"},
        source_slug="rdveikals-phones",
        category="phones",
    )
    assert fields["availability"] == "in_stock", "the page said InStock"


def test_a_code_in_days_cannot_tell_to_order_from_gone(event_loop):
    """Measured: in days the shop's own word was `PreOrder` 923 times and `OutOfStock` 40,
    with `10day` appearing as both. The cheap pass is wrong for 2.9% of this shop and the
    full pass corrects it — cheap being cheap, stated rather than hidden behind `unknown`."""
    fields = read(
        {"id": "1", "delivery_code": "10day", "price": "9.99", "currency": "EUR"},
        source_slug="rdveikals-phones",
        category="phones",
    )
    assert fields["availability"] == "preorder"


# --- colour, once the registry knows the word ---


def with_colours(**over) -> dict:
    from types import MappingProxyType

    from app.features.offers.normalization.rules import Vocabulary

    return Vocabulary(
        colours=MappingProxyType(
            {
                "melna": "black",
                "black": "black",
                "zila": "blue",
                "blue": "blue",
                "melna / oranža": "black-orange",
                "sand dune": "beige",
            }
        ),
        **over,
    )


def test_colour_comes_from_the_field_and_resolves(event_loop):
    """The shop states it rather than leaving it in a title, in 37 forms rather than the
    358 a title yields — which is what made this rule writable at all."""
    fields = read(
        {**parsed(), "specs": {"Kopējie parametri / Krāsa": "Melna"}},
        source_slug="rdveikals-phones",
        category="phones",
        vocabulary=with_colours(),
    )
    assert fields["identity"]["color"] == "black"


def test_a_two_tone_case_is_its_own_colour(event_loop):
    """`Melna / Oranža` is a different phone from `Melna`, with its own article number.
    Folding it into black would merge two products."""
    fields = read(
        {**parsed(), "specs": {"Kopējie parametri / Krāsa": "Melna / Oranža"}},
        source_slug="rdveikals-phones",
        category="phones",
        vocabulary=with_colours(),
    )
    assert fields["identity"]["color"] == "black-orange"


def test_a_marketing_name_resolves_to_nothing(event_loop):
    """`Obsidian` is Google's word for black and is not in the registry, on purpose: the
    pairs that could be learned from one shop include `evening blue` meaning grey."""
    fields = read(
        {**parsed(), "specs": {"Kopējie parametri / Krāsa": "Obsidian"}},
        source_slug="rdveikals-phones",
        category="phones",
        vocabulary=with_colours(),
    )
    assert "color" not in fields["identity"]


def test_a_name_with_no_capacity_loses_its_colour_instead(event_loop):
    """223 of the 241 such names end in a colour the registry knows. Cutting it is what
    turns a feature phone into a catalogue entry."""
    for name, expected in (
        ("GL695 Black", "GL695"),
        ("3210 Blue (paraugs)", "3210"),
        ("Armor X16 Pro Sand Dune", "Armor X16 Pro"),
    ):
        fields = read(
            {**parsed(), "name": name},
            source_slug="rdveikals-phones",
            category="phones",
            vocabulary=with_colours(),
        )
        assert fields["model"] == expected, name


def test_a_name_that_ends_in_no_colour_is_left_alone(event_loop):
    """Dropping a last word that is not a colour renames the phone."""
    fields = read(
        {**parsed(), "name": "Stone 4G"},
        source_slug="rdveikals-phones",
        category="phones",
        vocabulary=with_colours(),
    )
    assert fields["model"] is None


def test_without_the_registry_the_gap_stays_visible(event_loop):
    """A rule given no words does nothing, which is declining to guess rather than failing."""
    fields = read(
        {**parsed(), "name": "GL695 Black"},
        source_slug="rdveikals-phones",
        category="phones",
    )
    assert fields["model"] is None
