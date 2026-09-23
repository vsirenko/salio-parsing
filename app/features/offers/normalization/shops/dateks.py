"""dateks: what its codes and stock words mean, in every category it sells.

Moved out of `sources/dateks.py` on 23.09.2026, when a second category made the
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

SLUG = "dateks"
VERSION = "dateks-shop-1"


# What the shop has, in its own words. `Birojā` is the office counter and is stock like any
# other; `Pasūtāms` is the supplier's shelf, not ours.
IN_STOCK = ("Noliktavā", "Birojā")


TO_ORDER = ("Pasūtāms",)


def _barcode(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    return {"gtin": barcodes.pick(payload.get("barcodes"))}


def _availability(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    word = str(payload.get("availability") or "").strip()
    if word in IN_STOCK:
        return {"availability": "in_stock"}
    if word in TO_ORDER:
        return {"availability": "preorder"}
    return {}


RULESET = register(
    SHOP,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="dateks-gtin",
                layer=SHOP,
                why=(
                    "The card states its barcode more than once and under three different"
                    " labels — `EAN`, `Eans`, `GTIN` — in each of the two specification"
                    " blocks, so the channel hands over the list and this picks. Measured on"
                    " all 745: 643 (86.3%) name at least one code. 99 name more than one"
                    " that survives normalisation, and those are not duplicates — they are"
                    " the maker's code beside a distributor's, `8806097651079` and"
                    " `5413729250208` on one Samsung. Taking none of them was the first"
                    " instinct and the data refused it: of those 99, 88 carry a code one of"
                    " the other four shops also has, and `barcodes.pick` chooses that one 79"
                    " times. The 9 it gets wrong cost a match, not a wrong match — the code"
                    " it picked is one nobody else has — so dropping all 99 would give up 88"
                    " barcodes to avoid 9 misses."
                ),
                body=_barcode,
            ),
            Rule(
                id="dateks-availability",
                layer=SHOP,
                why=(
                    "The page's own schema.org block reads `InStock` for every one of the"
                    " 745, which is why the channel drops it and returns the shop's word"
                    " instead. The words disagree with it and with each other: 220"
                    " `Noliktavā`, 524 `Pasūtāms`, 1 `Birojā`. Reading the markup would"
                    " therefore report the whole category as in stock when 70.3% of it is to"
                    " order, which is the single fact a price comparison is asked for after"
                    " the price. `Birojā` is the office counter — stock that happens to be"
                    " in one place — and is not a third state."
                ),
                body=_availability,
            ),
        ),
    ),
)
