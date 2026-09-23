"""What a tablet listing means: the phone's axes, plus connectivity, and a model that carries
its screen size."""

from types import MappingProxyType

from app.features.offers.normalization import read
from app.features.offers.normalization.rules import Vocabulary

TABLETS = "tablets"
WORDS = Vocabulary(
    category_names=frozenset({"planšetdators"}),
    colours={"blue": "blue", "grey": "grey"},
)


def reading(title: str, model: str | None = None) -> dict:
    payload = {"name": title, "brand": "Apple"}
    if model is not None:
        payload["model"] = model
    return read(payload, category=TABLETS, vocabulary=WORDS)


def test_a_cellular_standard_in_the_name_is_the_cellular_tablet():
    assert (
        reading("Apple iPad Air 11 M4 Wi-Fi + Cellular 128GB Blue")["identity"]["connectivity"]
        == "cellular"
    )
    assert reading("Apple iPad Air 11 M4 Wi-Fi 128GB Blue")["identity"]["connectivity"] == "wifi"
    # A tablet saying what it lacks is not saying what it has.
    assert "connectivity" not in reading("Lenovo Idea Tab Pro 12.7 8/128 no 4G")["identity"]
    assert "connectivity" not in reading("TCL NXTPAPER 3.0 14.3 256 GB Grey")["identity"]


def screen(fields: dict) -> int | None:
    return fields["identity"].get("screen_inch")


def test_the_screen_is_an_axis_in_whole_inches_and_not_part_of_the_name():
    """`iPad Air 11"` and `iPad Air 13"` are two tablets, and a shop's `10.9"`, `11-inch` or
    `27,59cm (11")` are one screen. The name is `iPad Air` for all of them."""
    for title, model, inches in (
        ('Apple iPad Air 11" M4 Wi-Fi 128GB', "iPad Air M4", 11),
        ('Apple iPad Air 13" M4 Wi-Fi 128GB', "iPad Air M4", 13),
        ("11-inch iPad Air M4 Wi-Fi 128GB", "11-inch iPad Air M4", 11),
        ('Apple iPad Air M4 27,59cm (11"") 128GB', "iPad Air M4", 11),
        ('Apple iPad Air M4 10.9" 64GB', 'iPad Air M4 10.9"', 11),
    ):
        fields = reading(title, model)
        assert fields["model"] == "iPad Air M4", title
        assert screen(fields) == inches, title
    # No size stated: no axis, and nothing is guessed.
    assert screen(reading("Apple iPad Air M4 Wi-Fi 128GB", "iPad Air M4")) is None


def test_connectivity_leaves_the_model_and_takes_its_plus_with_it():
    assert (
        reading(
            'Apple iPad mini (A17 Pro) 8.3" Wi-Fi + Cellular 128GB',
            "iPad mini (A17 Pro) Wi-Fi + Cellular",
        )["model"]
        == "iPad mini (A17 Pro)"
    )
    assert reading("Samsung Galaxy Tab S10 FE 5G 128GB", "Galaxy Tab S10 FE 5G")["model"] == (
        "Galaxy Tab S10 FE"
    )


def test_the_version_says_what_was_applied():
    assert read({"name": "x"}, category=TABLETS)["ruleset_version"] == "generic-3+tablets-8"


def test_a_quote_or_a_table_rule_at_the_edge_is_not_part_of_the_model():
    assert reading('"Acer Iconia A10 10.1" 128GB', '"Acer Iconia A10')["model"] == "Acer Iconia A10"
    assert reading('Acer | Iconia V11-21M | 11 " | Grey', "| Iconia V11-21M |")["model"] == (
        "Iconia V11-21M"
    )


def test_a_configuration_with_no_unit_still_ends_the_model():
    """`OPPO Pad 5 8+128 5G` states its memory and storage without a unit; bigbox's phone rule
    read that as a feature phone with no capacity and left the model empty."""
    fields = read(
        {"title": "OPPO Pad 5 8+128 5G", "brand": "Oppo"},
        source_slug="bigbox-tablets",
        shop_slug="bigbox",
        category=TABLETS,
        vocabulary=Vocabulary(brand_names=frozenset({"oppo"})),
    )
    assert fields["model"] == "Pad 5"


def test_a_non_breaking_hyphen_is_still_wi_fi():
    """1a and ksenukai write `Wi‑Fi` with U+2011."""
    assert reading("Apple iPad Air M4 Wi\u2011Fi 128GB")["identity"]["connectivity"] == "wifi"


def test_the_chip_stays_and_the_maker_goes_from_inside():
    """`iPad Air M3` and `M4` are two generations; Apple writes its chip `Apple M3`."""
    fields = read(
        {
            "title": 'Planšetdators Apple iPad Air 13" Apple M3 Wi-Fi + Cellular 1TB',
            "brand": "Apple",
        },
        source_slug="bigbox-tablets",
        shop_slug="bigbox",
        category=TABLETS,
        vocabulary=Vocabulary(
            category_names=frozenset({"planšetdators"}), brand_names=frozenset({"apple"})
        ),
    )
    assert fields["model"] == "iPad Air M3"
    assert screen(fields) == 13


def test_a_size_the_title_leaves_out_comes_from_the_shop_s_field():
    words = Vocabulary(attribute_names={"ekrāna diagonāle": "screen_inch"})
    fields = read(
        {
            "name": "Apple iPad Mini (A17 Pro) Wi-Fi 128GB",
            "model": "iPad Mini (A17 Pro)",
            "specs": {'Ekrāna diagonāle, "': "8.3"},
        },
        category=TABLETS,
        vocabulary=words,
    )
    assert fields["model"] == "iPad Mini (A17 Pro)"
    assert screen(fields) == 8


def test_cell_is_short_for_cellular():
    """rdveikals writes `WiFi+Cell` on 9 of its 584 tablets."""
    fields = reading('iPad Pro 13" M5 WiFi+Cell 256GB Silver', 'iPad Pro 13" M5 WiFi+Cell')
    assert fields["identity"]["connectivity"] == "cellular"
    assert fields["model"] == "iPad Pro M5"


def radio(**fields: str) -> str | None:
    words = Vocabulary(
        attribute_names=MappingProxyType(
            {
                "mobilie sakari": "connectivity",
                "3g savienojums": "connectivity",
                "4g savienojums": "connectivity",
                "5g savienojums": "connectivity",
                "bezvadu pieslēgumi / mobīlo datu pārraide": "connectivity",
            }
        ),
        values=MappingProxyType(
            {
                "connectivity": MappingProxyType(
                    {"nē": "wifi", "nav": "wifi", "jā": "cellular", "ir": "cellular"}
                )
            }
        ),
    )
    return read({"name": "Tablet", "specs": fields}, category=TABLETS, vocabulary=words)[
        "identity"
    ].get("connectivity")


def test_a_yes_or_a_no_is_read_through_the_registry():
    """Four shops answer "has it a modem?" in fields, three of them with a word."""
    assert radio(**{"Mobilie sakari": "Nav"}) == "wifi"
    assert radio(**{"Mobilie sakari": "Ir"}) == "cellular"
    assert radio(**{"Bezvadu pieslēgumi / Mobīlo datu pārraide": "5G"}) == "cellular"
    # A word the registry does not know says nothing.
    assert radio(**{"Mobilie sakari": "Varbūt"}) is None


def test_a_no_for_one_standard_is_not_a_no_for_the_modem():
    """ksenukai answers for 3G and 4G and never for 5G: nine of its 5G tablets read as
    Wi-Fi when a no for 4G was taken as a no for everything."""
    assert radio(**{"3G savienojums": "Nē", "4G savienojums": "Nē"}) is None
    assert (
        radio(**{"3G savienojums": "Nē", "4G savienojums": "Nē", "5G savienojums": "Nē"}) == "wifi"
    )
    assert radio(**{"3G savienojums": "Nē", "4G savienojums": "Jā"}) == "cellular"


def ipad(title: str, model: str) -> str | None:
    return read(
        {"name": title, "brand": "Apple", "model": model}, category=TABLETS, vocabulary=WORDS
    ).get("model")


def test_an_ipad_s_model_names_its_generation():
    """`iPad Pro` is five machines: 60 entries were made from models naming the line only."""
    # bm writes the year after the capacity, where the cut took it off.
    assert ipad("Apple iPad Pro 12.9 Wi-Fi 2TB Silver (2022) MP273HC/A", "iPad Pro") == (
        "iPad Pro (2022)"
    )
    assert ipad("Apple iPad 10.9 Wi-Fi 64GB 10th Gen Silver (2022)", "iPad") == "iPad 10th Gen"
    # A model that already names it is left alone.
    assert ipad("Apple iPad Air 11 M3 128GB Blue", "iPad Air M3") == "iPad Air M3"
    # A title naming none: no model, rather than one that is five machines.
    assert not ipad("Apple iPad Pro 9.7 32GB Gold", "iPad Pro")


def test_the_glass_is_part_of_an_ipad_pro_s_model():
    """Standard and nano-texture glass are two tablets; the catalogue held the standard one
    under two names and filed rdveikals' nano one, glass written after the capacity, under
    the standard."""
    assert ipad(
        'Apple iPad Pro 13" M5 256GB WiFi w/Standard Glass', "iPad Pro M5 With Standard Glass"
    ) == ("iPad Pro M5")
    assert ipad('Apple iPad Pro 11" M5 WiFi+Cell 2TB Nano-texture glass Silver', "iPad Pro M5") == (
        "iPad Pro M5 Nano-texture"
    )
    # `standard` alone is not about the glass.
    assert (
        read(
            {
                "name": "Samsung Galaxy Tab S9 FE Standard Edition 128GB",
                "model": "Galaxy Tab S9 FE Standard Edition",
            },
            category=TABLETS,
        )["model"]
        == "Galaxy Tab S9 FE Standard Edition"
    )
