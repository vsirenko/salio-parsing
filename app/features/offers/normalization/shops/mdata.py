"""mdata: what its codes and stock words mean, in every category it sells.

Moved out of `sources/mdata.py` on 23.09.2026, when a second category made the
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

SLUG = "mdata"
VERSION = "mdata-shop-1"


# What this shop says instead of whether it has the thing. Both mean it can be bought.
SHIPS_IN = ("VEIKALĀ", "1-2 days", "3-5 days")


def _barcode(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    return {"gtin": barcodes.pick(payload.get("barcodes"))}


def _availability(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    flag = str(payload.get("availability") or "").strip()
    return {"availability": "in_stock"} if flag in SHIPS_IN else {}


RULESET = register(
    SHOP,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="mdata-barcode",
                layer=SHOP,
                why=(
                    "The shop has two of its own `schema.org` fields the wrong way round:"
                    " `model` holds the barcode and `mpn` an internal number, and the"
                    " maker's part number is in the prose of `description` behind"
                    " `Manufacturer code:`. So nothing is trusted by the name of the field"
                    " it came in: the channel hands the numbers over as a list and"
                    " `barcodes.pick` chooses, as it does for every shop. All 98 carry at"
                    " least one candidate and the check digit sorts them."
                ),
                body=_barcode,
            ),
            Rule(
                id="mdata-availability",
                layer=SHOP,
                why=(
                    "This shop says how soon rather than whether: `1-2 days` on 90 of the 98"
                    " and `3-5 days` on the other 8, with `VEIKALĀ` for what is on a shelf."
                    " All three mean it can be bought. There is no out-of-stock word here"
                    " because the shop does not list what it has not got — and if one ever"
                    " appears it will read as `unknown` and be visible, which is the right"
                    " way round. Not from the page's own JSON-LD, which reads `InStock` for"
                    " everything: the fifth shop in a row whose structured data means it"
                    " will sell the thing rather than that it has it."
                ),
                body=_availability,
            ),
        ),
    ),
)
