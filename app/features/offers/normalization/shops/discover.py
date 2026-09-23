"""discover: what its codes and stock words mean, in every category it sells.

Moved out of `sources/discover.py` on 23.09.2026, when a second category made the
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

SLUG = "discover"
VERSION = "discover-shop-1"


def _availability(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    return {"availability": "in_stock"} if str(payload.get("in_stock") or "").strip() == "1" else {}


RULESET = register(
    SHOP,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="discover-availability",
                layer=SHOP,
                why=(
                    "`in_stock` is `1` on all 560, so as a field it says nothing — and as a"
                    " fact it says everything: the export holds what the shop is willing to"
                    " sell, and a product that leaves it has left the shop. Read here rather"
                    " than left to generic, whose table knows `true` and `yes` and not `1`,"
                    " so all 560 were arriving `unknown` on a channel that declares it"
                    " delivers availability. What this shop cannot say is the difference"
                    " between stock and to-order; it does not distinguish them either."
                ),
                body=_availability,
            ),
        ),
    ),
)
