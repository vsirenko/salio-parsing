"""1a.lv phones — the group's second shop, through the same index engine.

Served from a real record captured on 22.09.2026. Nothing here reaches the network.
"""

from types import MappingProxyType

from app.features.offers.normalization import read
from app.features.offers.normalization.rules import Vocabulary

SLUG = "onea-phones"


def vocabulary() -> Vocabulary:
    return Vocabulary(
        category_names=frozenset({"mobilais", "telefons", "viedtālrunis"}),
        colours=MappingProxyType(
            {"melna": "black", "melns": "black", "zila": "blue", "oranža": "orange"}
        ),
    )


def parsed(title: str, brand: str) -> dict:
    return read(
        {"id": "1", "title_lv": title, "brand": brand, "price": "199.00", "currency": "EUR"},
        source_slug=SLUG,
        shop_slug="onea",
        category="phones",
        vocabulary=vocabulary(),
    )


def test_the_model_is_the_head_without_the_kind_the_brand_or_the_code():
    """This index has no `Modelis` column — the sister shop's does, and that is where its
    model comes from on every product. Here the title is the only source."""
    for title, brand, expected in (
        (
            "Mobilais telefons Samsung Galaxy S26 Ultra 5G SM-S948BZKDEUE, 256 GB, melna krās.",
            "Samsung",
            "Galaxy S26 Ultra 5G",
        ),
        ("Mobilais telefons Apple iPhone 15 MTP03PX/A, 128 GB, melns krās.", "Apple", "iPhone 15"),
        ("Mobilais telefons Poco X8 Pro MZB0MY8EU, 256 GB, melna krās.", "Poco", "X8 Pro"),
        ("Mobilais telefons Nokia 3210, 128 MB, melna krās.", "Nokia", "3210"),
    ):
        assert parsed(title, brand)["model"] == expected, title


def test_the_part_number_is_the_rung_this_shop_lives_on():
    """It publishes no barcode at all, so the strongest signal is missing from every one of
    its products and a model string alone is a family rather than a thing to buy."""
    assert (
        parsed(
            "Mobilais telefons Samsung Galaxy S26 Ultra 5G SM-S948BZKDEUE, 256 GB, melna krās.",
            "Samsung",
        )["mpn"]
        == "SM-S948BZKDEUE"
    ), "the maker's prefix is part of the code"
    assert (
        parsed("Mobilais telefons Apple iPhone 15 MTP03PX/A, 128 GB, melns krās.", "Apple")["mpn"]
        == "MTP03PX/A"
    )


def test_a_title_with_no_code_yields_no_part_number():
    assert parsed("Mobilais telefons Nokia 3210, 128 MB, melna krās.", "Nokia")["mpn"] is None


def test_the_colour_rule_is_the_sister_shop_s_own():
    """One group, one title. Two copies of the rule would be two places to fix the day the
    group changes its wording."""
    from app.features.offers.normalization.sources.ksenukai import color_from_title
    from app.features.offers.normalization.sources.onea import RULESET

    shared = next(rule for rule in RULESET.rules if rule.id == "onea-color-from-title")
    assert shared.body is color_from_title
    assert (
        parsed("Mobilais telefons Poco X8 Pro MZB0MY8EU, 256 GB, melna krās.", "Poco")["identity"][
            "color"
        ]
        == "black"
    )


def test_a_marketing_colour_stays_unresolved():
    fields = parsed(
        "Mobilais telefons Apple iPhone 17 Pro Max MFYP4HX/A, 256 GB, cobalt violet krās.", "Apple"
    )
    assert "color" not in fields["identity"]
    assert fields["model"] == "iPhone 17 Pro Max", "the rest of the title still reads"


def test_the_version_says_what_was_applied():
    assert (
        parsed("Mobilais telefons Nokia 3210, 128 MB, melna krās.", "Nokia")["ruleset_version"]
        == "generic-2+phones-13+onea-shop-1+onea-5"
    )


def tablet(title: str, brand: str) -> str | None:
    return read(
        {
            "id": "1",
            "title_lv": title,
            "title": title,
            "brand": brand,
            "price": "199.00",
            "currency": "EUR",
        },
        source_slug="onea-tablets",
        shop_slug="onea",
        category="tablets",
        vocabulary=Vocabulary(category_names=frozenset({"planšetdators"})),
    ).get("model")


def test_a_tablet_s_head_loses_its_codes_wherever_they_sit():
    """Titles as the group wrote them on 23.09.2026; bigbox names each without the code."""
    assert tablet('Planšetdators Xiaomi Pad 8 71703, 11.2", 8GB/256GB, zaļa krās.', "Xiaomi") == (
        "Pad 8 11"
    )
    assert tablet('Planšetdators Samsung Galaxy Tab S11 X730, 11", 12GB/128GB', "Samsung") == (
        "Galaxy Tab S11 11"
    )
    assert tablet(
        'Planšetdators Samsung Galaxy Tab A11 SM-X135FZAAEEE Enterprise Edition, 8.6"', "Samsung"
    ) == ("Galaxy Tab A11 Enterprise Edition 9")
    assert tablet('Planšetdators Lenovo Yoga Tab Plus ZAEG0022PL TB520FU, 12.7"', "Lenovo") == (
        "Yoga Tab Plus 13"
    )
    assert tablet('Planšetdators Huawei MatePad 53013UJQ, 11.5", 8GB/128GB', "Huawei") == (
        "MatePad 12"
    )


def test_a_number_that_is_the_name_stays():
    assert tablet('Planšetdators Kruger&Matz Fun 1008, 10", 4GB/64GB', "Kruger&Matz") == (
        "Fun 1008 10"
    )
    assert tablet('Planšetdators Acer Iconia V11-21M, 11", 8GB/128GB', "Acer") == (
        "Iconia V11-21M 11"
    )
    assert tablet('Planšetdators XORO MegaPad 2404v7, 24", 4GB/64GB', "XORO") == "MegaPad 2404v7"
