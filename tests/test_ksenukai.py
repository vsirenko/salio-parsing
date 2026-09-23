"""ksenukai.lv phones, read through the shop's search index.

Served from a real response captured on 21.09.2026, so the shapes are the shop's own —
including the ones that surprised us. Nothing here reaches the network.
"""

import json
import pathlib

import httpx2
import pytest

from app.features.runs.channels.ksenukai import PAGE, Ksenukai
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import Job, Kind

FIXTURE = json.loads((pathlib.Path(__file__).parent / "fixtures/ksenukai_phones.json").read_text())
JOB = Job(
    run_id=1,
    source_id=1,
    source_slug="ksenukai-phones",
    shop_slug="ksenukai",
    kind=Kind.FULL,
    access="wholesale",
    decode="private_api",
    base_url=None,
    market_codes=["LV"],
    delivers=["catalogue", "price", "availability"],
)


def index(pages: list[dict], seen: list[dict] | None = None) -> Fetcher:
    """A stub index that hands back the given pages in order."""

    async def serve(request: httpx2.Request) -> httpx2.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx2.Response(200, json=pages[min(len(seen or []) - 1, len(pages) - 1)])

    return Fetcher(rate=0, client=httpx2.AsyncClient(transport=httpx2.MockTransport(serve)))


def one(external_id: str = "1102611") -> dict:
    item = next(i for i in FIXTURE["items"] if str(i["id"]) == external_id)
    return item


async def parsed(external_id: str = "1102611") -> dict:
    channel = Ksenukai()
    async with index([FIXTURE], []) as fetcher:
        listings = await channel.discover(fetcher, JOB)
    listing = next(x for x in listings if x.external_id == external_id)
    channel_snapshot = await channel.fetch(None, listing)
    return channel.parse(channel_snapshot)


# --- discovery ---


def test_discovery_walks_the_pages(event_loop):
    channel = Ksenukai()
    sent: list[dict] = []
    first = {**FIXTURE, "total": 5, "offset": 0}
    second = {**FIXTURE, "items": FIXTURE["items"][:2], "total": 5, "offset": 3}

    async def run():
        async with index([first, second], sent) as fetcher:
            return await channel.discover(fetcher, JOB)

    listings = event_loop.run_until_complete(run())
    assert len(listings) == 5
    # Paged by offset, asking for the index's own maximum.
    assert [body["offset"] for body in sent] == [0, 3]
    assert sent[0]["limit"] == PAGE
    assert sent[0]["filters"]["categories_lv_last"] == ["Mobilie telefoni"]
    # Facets are the shop's filter sidebar; we draw none and asking makes pages heavier.
    assert sent[0]["modifiers"] == {"facets": False, "refiners": False}


def test_a_listing_carries_the_whole_record(event_loop):
    """On a wholesale channel there is no card to open: the index is the detail."""
    channel = Ksenukai()

    async def run():
        async with index([FIXTURE], []) as fetcher:
            return await channel.discover(fetcher, JOB)

    listings = event_loop.run_until_complete(run())
    assert listings[0].external_id == "1102611"
    assert listings[0].url.startswith("https://www.ksenukai.lv/p/")
    assert listings[0].card["title_lv"]


# --- reading ---


def test_the_model_comes_from_the_encoded_columns(event_loop):
    """The field brand-and-model matching stands on, and the `attributes` list lacks it."""
    fields = event_loop.run_until_complete(parsed())
    assert fields["attributes"]["Modelis"] == "Hammer Rock"
    # It is nowhere in the list the index calls `attributes`.
    assert not any((a.get("name") or {}).get("lv") == "Modelis" for a in one()["attributes"])


def test_the_list_wins_where_both_have_a_name(event_loop):
    """It carries the unit; the encoded column carries a dirtier name and a bare number."""
    fields = event_loop.run_until_complete(parsed())
    assert fields["attributes"]["Ekrāna izmērs"] == '2.4 "'
    assert fields["attributes"]['Ekrāna izmērs, "'] == "2.4"


def test_a_repeated_name_keeps_both_values(event_loop):
    """About a third of these list a camera twice, and the last one would win silently."""
    channel = Ksenukai()
    item = {
        **one(),
        "attributes": [
            {"name": {"lv": "Aizmugurējā kamera"}, "value": {"lv": "50 MP"}},
            {"name": {"lv": "Aizmugurējā kamera"}, "value": {"lv": "12 MP"}},
        ],
    }
    page = {"total": 1, "items": [item]}

    async def run():
        async with index([page], []) as fetcher:
            listings = await channel.discover(fetcher, JOB)
        return channel.parse(await channel.fetch(None, listings[0]))

    fields = event_loop.run_until_complete(run())
    assert fields["attributes"]["Aizmugurējā kamera"] == "50 MP; 12 MP"


def test_the_barcode_is_handed_over_untouched(event_loop):
    """Choosing between these is a reading decision, not the shop's shape.

    Check digits and reserved prefixes are a standard. Deciding here would bake one
    interpretation into the only copy of the bytes there is, and every other channel would
    have to make the same decision separately and differently.
    """
    fields = event_loop.run_until_complete(parsed())
    assert fields["alternative_codes"] == [
        "1226772",
        "590298361774",
        "5902983617747",
        "Y00001210299",
    ]
    assert "ean" not in fields
    assert "gtin" not in fields


def test_the_shops_own_fields_survive(event_loop):
    fields = event_loop.run_until_complete(parsed())
    assert fields["brand"] == "MyPhone"
    assert fields["title"].startswith("Telefons ar pogām MyPhone Hammer Rock")
    assert fields["price"] == 42.9
    # The loyalty price is kept beside the ordinary one, never instead of it.
    assert fields["price_loyalty"] == 34.9
    assert fields["in_stock"] is True
    assert "Mobilie telefoni" in fields["categories"]


def test_a_real_phone_reads_as_a_phone(event_loop):
    fields = event_loop.run_until_complete(parsed("1268710"))
    assert fields["brand"] == "Apple"
    assert fields["attributes"]["Modelis"]
    assert fields["price"]


# --- the snapshot ---


def test_the_snapshot_holds_the_record_so_a_reparse_works(event_loop):
    channel = Ksenukai()

    async def run():
        async with index([FIXTURE], []) as fetcher:
            listings = await channel.discover(fetcher, JOB)
        return await channel.fetch(None, listings[0])

    snapshot = event_loop.run_until_complete(run())
    assert snapshot.part("index") is not None
    # Parsing it again gives the same thing, with no network at all.
    assert channel.parse(snapshot)["attributes"]["Modelis"] == "Hammer Rock"


def test_a_snapshot_without_its_record_is_an_error():
    from app.features.runs.channel import Snapshot

    with pytest.raises(ValueError, match="no index record"):
        Ksenukai().parse(Snapshot(external_id="x", parts=[]))


# --- colour out of the one place this shop always puts it ---


def with_colours():
    from types import MappingProxyType

    from app.features.offers.normalization.rules import Vocabulary

    return Vocabulary(
        colours=MappingProxyType(
            {
                "melns": "black",
                "melna": "black",
                "balts": "white",
                "oranža": "orange",
                "zila": "blue",
                "black": "black",
                "white": "white",
                "orange": "orange",
                "blue": "blue",
                "black-orange": "black-orange",
            }
        )
    )


def coloured(title: str):
    from app.features.offers.normalization import read

    return read(
        {"id": "1", "title_lv": title, "price": "1", "currency": "EUR"},
        source_slug="ksenukai-phones",
        shop_slug="ksenukai",
        category="phones",
        vocabulary=with_colours(),
    )["identity"].get("color")


def test_the_colour_is_read_from_the_fixed_end_of_the_title():
    """This shop publishes no colour field, and colour is one of the two axes a phone is
    told apart by. Its titles end the same way on 487 of 525."""
    assert coloured("Mobilais telefons Samsung Galaxy Xcover6 Pro, 128 GB, melns krās.") == "black"
    assert coloured("Telefons ar pogām MyPhone Halo 3, 32 MB, balts krās.") == "white"


def test_a_case_in_two_colours_says_the_word_twice():
    """`melna krās./oranža krās.` is its own product with its own article number, so it is
    its own value rather than the first half of one."""
    assert coloured("Telefons MyPhone Hammer, 32 MB, melna krās./oranža krās.") == "black-orange"


def test_a_marketing_name_is_left_unresolved():
    """`glacier`, `obsidian`, `cobalt violet` are what this shop invents. Resolving them by
    guessing splits one product into several, confidently — the refusal `phones-color` was
    written around."""
    assert coloured("Mobilais telefons Apple iPhone 17, 256 GB, glacier krās.") is None


def test_half_a_pair_is_not_an_answer():
    """A pairing the registry has never agreed to is not a colour, and the half that did
    resolve is the wrong answer rather than a partial one."""
    assert coloured("Telefons X, 32 MB, melna krās./nezināma krās.") is None


def test_a_title_that_names_no_colour_yields_none():
    assert coloured("Mobilais telefons bez krāsas") is None


def test_the_word_for_colour_is_written_three_ways():
    """`melna krās.`, `sudraba kr.`, `melnā krāsā` — a title that uses the short one is not
    a title without a colour, and reading only one form left 38 listings colourless."""
    assert coloured("Mobilais telefons X, 128 GB, melns kr.") == "black"
    assert coloured("Mobilais telefons X, 128 GB, melns krāsā") == "black"
    assert coloured("Mobilais telefons X, 128 GB, melns krās.") == "black"


def test_a_marketing_word_in_front_of_a_colour_is_dropped():
    """Samsung's `Awesome` line, in Latvian. The colour is the head of the phrase and comes
    last, so the front can be dropped without this module knowing what `lieliski` means."""
    from types import MappingProxyType

    from app.features.offers.normalization import colours
    from app.features.offers.normalization.rules import Vocabulary

    words = Vocabulary(
        colours=MappingProxyType({"pelēka": "grey", "tumši zila": "dark-blue", "zila": "blue"})
    )
    assert colours.resolve("lieliski pelēka", words) == "grey"
    assert colours.resolve("lieliski tumši zila", words) == "dark-blue"


def test_an_invented_word_at_the_end_is_not_dropped():
    """`silver shadow` and `night sky` put the invention last. Guessing from the first word
    instead would read `arctic seal` as a colour."""
    from types import MappingProxyType

    from app.features.offers.normalization import colours
    from app.features.offers.normalization.rules import Vocabulary

    words = Vocabulary(colours=MappingProxyType({"silver": "silver", "black": "black"}))
    assert colours.resolve("silver shadow", words) is None
    assert colours.resolve("arctic seal", words) is None
    assert colours.resolve("midnight black", words) == "black"


def test_a_title_that_leaves_the_word_out_still_names_a_colour():
    """The group writes it on almost every title and then, on thirty-four, simply does not:
    `…, 512 GB, krēmkrāsa`. The colour sits where it always sits, and the registry is still
    the gate — a last segment that is not a colour gives nothing."""
    assert coloured("Mobilais telefons Samsung Galaxy Fold 8 5G -, 256 GB, melna") == "black"
    assert coloured("Mobilais telefons X, 128 GB, nezināms") is None
