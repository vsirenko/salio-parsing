"""bigbox.lv phones, read through the shop's search index.

Served from a real response captured on 22.09.2026, facet labels and all. Nothing here
reaches the network.
"""

import json
import pathlib

import httpx2
import pytest

from app.features.offers.normalization import read
from app.features.runs.channels.bigbox import PAGE, SITE, Bigbox
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import Job, Kind

FIXTURE = json.loads((pathlib.Path(__file__).parent / "fixtures/bigbox_phones.json").read_text())
NAMES = FIXTURE["_facet_names"]
FACETS = [{"key": key, "label": label} for key, label in NAMES.items()]
JOB = Job(
    run_id=1,
    source_id=1,
    source_slug="bigbox-phones",
    kind=Kind.FULL,
    access="wholesale",
    decode="private_api",
    base_url=None,
    market_codes=["LV"],
    delivers=["catalogue", "price", "availability"],
)


def index(pages: list[dict], sent: list[dict] | None = None) -> Fetcher:
    """A stub index: the first request asks for facets, the rest for items."""

    async def serve(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        if sent is not None:
            sent.append(body)
        if body.get("modifiers", {}).get("facets"):
            return httpx2.Response(200, json={"total": 5, "items": [], "facets": FACETS})
        index_of = max(0, len([b for b in (sent or []) if not b["modifiers"]["facets"]]) - 1)
        return httpx2.Response(200, json=pages[min(index_of, len(pages) - 1)])

    return Fetcher(rate=0, client=httpx2.AsyncClient(transport=httpx2.MockTransport(serve)))


def discover(event_loop, pages=None, sent=None):
    channel = Bigbox()

    async def run():
        async with index(pages or [FIXTURE], sent if sent is not None else []) as fetcher:
            return await channel.discover(fetcher, JOB)

    return channel, event_loop.run_until_complete(run())


def parsed(event_loop, external_id: str = "1032119") -> dict:
    channel, listings = discover(event_loop)
    listing = next(x for x in listings if x.external_id == external_id)
    return channel.parse(event_loop.run_until_complete(channel.fetch(None, listing)))


# --- discovery ---


def test_the_names_are_asked_for_once_and_the_pages_after(event_loop):
    """Facet labels are the same for every product; asking per page pays for them again."""
    sent: list[dict] = []
    _, listings = discover(
        event_loop, [{**FIXTURE, "total": 5}, {**FIXTURE, "items": FIXTURE["items"][:2]}], sent
    )

    assert len(listings) == 5
    assert [b["modifiers"]["facets"] for b in sent] == [True, False, False]
    assert [b["offset"] for b in sent[1:]] == [0, 3]
    assert sent[1]["limit"] == PAGE
    assert sent[1]["filters"]["categories_ids"] == [1549]
    # Ordered explicitly, or paging by offset skips some products and repeats others.
    assert sent[1]["sort"] == [{"id": "asc"}]


def test_a_listing_carries_the_record_and_the_names(event_loop):
    _, listings = discover(event_loop)
    assert listings[0].external_id == "1032119"
    assert listings[0].url.startswith(SITE)
    assert listings[0].card["item"]["ean_code"]
    assert listings[0].card["names"]["attribute_string_466"]


# --- reading the shop's shape ---


def test_numbered_attributes_get_the_shop_s_own_labels(event_loop):
    """`attribute_string_466` is internal storage and nothing in the record says so."""
    fields = parsed(event_loop)
    assert "Iekšējā atmiņa, GB" in fields["attributes"]
    assert "Operatīvā atmiņa, (RAM)" in fields["attributes"]


def test_an_unlabelled_attribute_keeps_the_key_the_shop_gave_it(event_loop):
    """Only filterable attributes are named. An invented name would be our vocabulary
    wearing theirs."""
    fields = parsed(event_loop)
    assert fields["attributes"]["attribute_string_23"] == "Oukitel WP56 Black"


def test_the_shops_own_fields_survive(event_loop):
    fields = parsed(event_loop)
    assert fields["brand"] == "Oukitel"
    assert fields["title"].startswith("Tālrunis Oukitel WP56")
    assert fields["ean_code"] == "6941749811523"
    assert fields["price"] == 375.74
    assert fields["in_stock"] is False


def test_the_barcode_is_handed_over_untouched(event_loop):
    """Deciding which of a shop's numbers is a real GTIN is a reading decision."""
    fields = parsed(event_loop)
    assert "gtin" not in fields


# --- the snapshot has to be enough on its own ---


def test_the_snapshot_carries_the_names_so_a_reparse_needs_nothing_else(event_loop):
    """A snapshot that needed a second document to be readable would not be a snapshot."""
    channel, listings = discover(event_loop)
    snapshot = event_loop.run_until_complete(channel.fetch(None, listings[0]))

    assert {part.role for part in snapshot.parts} == {"index", "names"}
    assert "Iekšējā atmiņa, GB" in channel.parse(snapshot)["attributes"]


def test_a_snapshot_without_its_record_is_an_error():
    from app.features.runs.channel import Snapshot

    with pytest.raises(ValueError, match="no index record"):
        Bigbox().parse(Snapshot(external_id="x", parts=[]))


# --- what the rules make of it ---


def test_the_rules_find_what_generic_cannot(event_loop):
    fields = parsed(event_loop)
    generic = read(fields)
    assert generic["gtin"] is None
    assert generic["mpn"] is None

    full = read(fields, source_slug="bigbox-phones", category="phones")
    assert full["gtin"] == "6941749811523"
    assert full["mpn"] == "Oukitel WP56 Black"
    assert full["ruleset_version"] == "generic-1+phones-5+bigbox-4"


def test_the_phone_line_is_not_the_model(event_loop):
    """`Galaxy S26` is the Ultra, the Plus and the plain one alike: reading it as the model
    would make one ambiguous pile out of a whole family. The model comes from the title."""
    fields = {**parsed(event_loop), "attributes": {"Tālruņa modelis": "Galaxy S26"}}
    full = read_it(fields)

    assert full["model"] == "WP56 5G"
    # The line is working state the layer below the brand selects on, and is not stored.
    assert "_line" not in full


def test_capacity_comes_from_the_category_not_the_shop(event_loop):
    fields = parsed(event_loop)
    full = read(fields, source_slug="bigbox-phones", category="phones")
    assert full["identity"]["storage_mb"] == 512 * 1024


# --- reading a model out of a title ---


def read_it(fields, words=("telefons", "tālrunis", "viedtālrunis", "mobilais")):
    from app.features.offers.normalization import Vocabulary

    return read(
        fields,
        source_slug="bigbox-phones",
        category="phones",
        vocabulary=Vocabulary(category_names=frozenset(words)),
    )


def test_the_model_is_what_is_left_after_the_kind_and_the_brand(event_loop):
    """`[kind] [brand] MODEL CAPACITY COLOUR`, and the colour falls off with the capacity."""
    fields = parsed(event_loop)
    assert fields["title"] == "Tālrunis Oukitel WP56 5G 12GB/512GB Black"
    assert read_it(fields)["model"] == "WP56 5G"


def test_the_words_naming_the_category_come_from_the_registry(event_loop):
    """They are Latvian. A rule carrying them is vocabulary in code, which is the thing we
    keep having to take back out."""
    fields = parsed(event_loop)
    # Without the words, the kind stays on the front of the name.
    assert read_it(fields, words=())["model"] == "Tālrunis Oukitel WP56 5G"


def test_working_memory_written_into_the_capacity_does_not_land_on_the_model(event_loop):
    """`4/128GB` is two numbers and one unit, so cutting at the unit leaves `4/` behind."""
    fields = {**parsed(event_loop), "title": "Viedtālrunis Oukitel G3 4/128GB Black"}
    assert read_it(fields)["model"] == "G3"


def test_a_diagonal_is_a_specification_not_a_name(event_loop):
    fields = {**parsed(event_loop), "title": 'Viedtālrunis Oukitel G3 6" 4/128GB 6300mAh'}
    assert read_it(fields)["model"] == "G3"


def test_a_title_with_no_capacity_yields_no_model(event_loop):
    """On this shop that is a feature phone or a desk phone. There the colour runs into the
    name, so two colours of one handset would become two products."""
    fields = {**parsed(event_loop), "title": "Mobilais tālrunis Nokia 3210 LTE Gold"}
    assert read_it(fields)["model"] is None


def test_the_names_agree_with_what_the_other_shop_states(event_loop):
    """Which is what lets one product hold both shops' listings."""
    for title, expected in (
        ("Telefons Apple iPhone 17 Pro 256GB Deep Blue", "iPhone 17 Pro"),
        ("Telefons Apple iPhone 18 Pro Max 512GB Black", "iPhone 18 Pro Max"),
        ("Telefons Samsung Galaxy S26 Ultra 5G 1TB Pink", "Galaxy S26 Ultra 5G"),
    ):
        fields = {**parsed(event_loop), "title": title, "brand": title.split()[1]}
        assert read_it(fields)["model"] == expected, title


def test_a_pair_sharing_one_unit_is_two_sizes(event_loop):
    """`128/4 GB` is capacity then memory with a single unit at the end, and only the `4`
    is spelled as a size. Reading the spelled half filed a 128 GB phone as having four —
    found because another shop sold the same barcode and said 128."""
    from app.features.offers.normalization.categories.phones import _megabytes

    assert _megabytes("Oukitel G1S tālrunis, 128/4 GB, melns") == 128 * 1024
    assert _megabytes("Samsung Galaxy S25+ 5G tālrunis, 512/12 GB, zils") == 512 * 1024
    # The other order still reads the same way: the larger of the pair is the capacity.
    assert _megabytes("Oukitel WP56 5G 12GB/512GB Black") == 512 * 1024
    assert _megabytes("Nokia 3210 LTE Gold") is None
