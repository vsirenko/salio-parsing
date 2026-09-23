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
        == "generic-2+phones-12+onea-2"
    )
