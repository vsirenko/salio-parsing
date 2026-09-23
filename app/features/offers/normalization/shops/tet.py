"""tet: what its codes and stock words mean, in every category it sells.

Moved out of `sources/tet.py` on 23.09.2026, when a second category made the
difference matter: these rules are true of the shop, and a new category of it would
otherwise have been read without them. How the shop names a product stays there.
"""

from typing import Any

from app.features.offers.normalization.rules import (
    SHOP,
    Rule,
    Ruleset,
    Vocabulary,
    register,
)

SLUG = "tet"
VERSION = "tet-shop-1"


# The shop's flag for a product it has not got yet. Nothing at all is the other state.
SOON = "Drīzumā"


def _availability(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    flag = str(payload.get("availability") or "").strip()
    return {"availability": "preorder" if flag == SOON else "in_stock"}


RULESET = register(
    SHOP,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="tet-availability",
                layer=SHOP,
                why=(
                    "This shop says what it has not got and says nothing about what it has:"
                    " 8 of its 333 cards carry a `Drīzumā` flag and the other 325 carry no"
                    " flag at all. So an empty field is the answer here rather than a gap,"
                    " which is the opposite of every other channel and the reason this is"
                    " read rather than left to generic. Not from the page's own JSON-LD,"
                    " which reads `InStock` on all 40 sampled including the 3 the shop"
                    " itself flags as not yet in — the fourth shop in a row whose structured"
                    " data means it will sell the thing rather than that it has it."
                ),
                body=_availability,
            ),
        ),
    ),
)
