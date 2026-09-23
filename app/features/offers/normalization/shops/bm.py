"""bm: what its codes and stock words mean, in every category it sells.

Moved out of `sources/bm.py` on 23.09.2026, when a second category made the
difference matter: these rules are true of the shop, and a new category of it would
otherwise have been read without them. How the shop names a product stays there.
"""

import re
from typing import Any

from app.features.offers.normalization.rules import (
    SHOP,
    Rule,
    Ruleset,
    Vocabulary,
    register,
)

SLUG = "bm"
VERSION = "bm-shop-1"


# The shop's own words. It is a showroom that orders in, so `Pēc pasūtījuma` is its ordinary
# state rather than an exception.
IN_STOCK = ("Ir veikalā",)


TO_ORDER = ("Pēc pasūtījuma",)


# Apple's own code, as this shop appends it: `… Cosmic Orange MG8M4`. Upper case, four to
# six characters, at the very end.
APPLE_CODE = re.compile(r"\s([A-Z][A-Z0-9]{3,5})$")


APPLE = "apple"


def _availability(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    word = str(payload.get("availability") or "").strip()
    if word in IN_STOCK:
        return {"availability": "in_stock"}
    if word in TO_ORDER:
        return {"availability": "preorder"}
    return {}


def _part_number(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """Apple's code, which this shop writes into the name when it has no `mpn` field.

    Only for Apple, and only when the field is empty. Both halves are the measurement: the
    two sets never overlap on these 937, and the same pattern applied to the other brands
    matched twice and was wrong both times.
    """
    if fields.get("mpn"):
        return {}
    if (payload.get("brand") or "").strip().casefold() != APPLE:
        return {}
    found = APPLE_CODE.search((payload.get("name") or "").strip())
    return {"mpn": found.group(1)} if found else {}


RULESET = register(
    SHOP,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="bm-availability",
                layer=SHOP,
                why=(
                    "The record's `stock_status` reads `IN_STOCK` on 936 of 937, which is"
                    " Magento saying the shop will sell the thing rather than that it has"
                    " it. The shop states what it means in `availability_type` beside it:"
                    " 934 `Pēc pasūtījuma` and 3 `Ir veikalā`. This is a showroom that"
                    " orders in, so to-order is its ordinary state and reading the flag"
                    " instead would report a warehouse that does not exist."
                ),
                body=_availability,
            ),
            Rule(
                id="bm-apple-part-number",
                layer=SHOP,
                why=(
                    "Apple is where this shop is thinnest — 42 barcodes on 196 products,"
                    " against 74% for Xiaomi — and its part number is missing on 155 of"
                    " them. It is not missing from the page: the shop appends Apple's own"
                    " code to the name, `iPhone 17 Pro 512GB Cosmic Orange MG8M4`, on 120 of"
                    " those 155. The two are never both present, which is what says the shop"
                    " writes the code in one place or the other, so reading the name where"
                    " the field is empty takes Apple from 41 part numbers to 161 (82.1%)."
                    " Restricted to Apple on purpose: the same pattern over the other 741"
                    " products matched twice and was part of the model both times"
                    " (`Emporia FN313`)."
                ),
                body=_part_number,
            ),
        ),
    ),
)
