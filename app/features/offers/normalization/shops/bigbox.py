"""bigbox: what its codes and stock words mean, in every category it sells.

Moved out of `sources/bigbox.py` on 23.09.2026, when a second category made the
difference matter: these rules are true of the shop, and a new category of it would
otherwise have been read without them. How the shop names a product stays there.
"""

from typing import Any

from app.features.offers.normalization import barcodes
from app.features.offers.normalization.rules import (
    SHOP,
    Rule,
    Ruleset,
    Vocabulary,
    register,
)

SLUG = "bigbox"
VERSION = "bigbox-shop-1"


# The record calls its manufacturer code by its raw column name: the index only labels the
# attributes it lets shoppers filter on, and this is not one of them.
MPN_KEY = "attribute_string_23"


def _barcode(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    return {"gtin": barcodes.pick(payload.get("ean_code"))}


def _part_number(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    value = (payload.get("attributes") or {}).get(MPN_KEY)
    return {"mpn": str(value).strip()[:100]} if value else {}


RULESET = register(
    SHOP,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="bigbox-barcode",
                layer=SHOP,
                why=(
                    "The barcode is a named field, `ean_code`, on 93.2% of these products —"
                    " but named something generic does not look for, so without this rule"
                    " the strongest signal the matcher has is invisible on all of them. It"
                    " also appears a second time as `attribute_string_15`, identical on"
                    " every product that has both; reading the named one means the"
                    " duplicate can be ignored rather than reconciled."
                ),
                body=_barcode,
            ),
            Rule(
                id="bigbox-part-number",
                layer=SHOP,
                why=(
                    "`attribute_string_23` holds the maker's own code on 91.9% of these"
                    " products, and the index never labels it — only filterable attributes"
                    " get a name in its facets. Of the values that are there, 85% look like"
                    " a code (`WP56-RD/OL`, `G3-OE/OL`) and 12.6% contain a space, which is"
                    " a shop having typed a name into a code field. Unlike ksenukai's"
                    " article numbers these are the manufacturer's, so they can agree with"
                    " another shop — the junk simply fails to match rather than matching"
                    " wrongly."
                ),
                body=_part_number,
            ),
        ),
    ),
)
