"""rdveikals: what its codes and stock words mean, in every category it sells.

Moved out of `sources/rdveikals.py` on 23.09.2026, when a second category made the
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

SLUG = "rdveikals"
VERSION = "rdveikals-shop-1"


# How soon the shop says it could hand the thing over: `15min`, `4hour`, `10day`.
_HOURS_OR_LESS = re.compile(r"^\d+(?:min|hour)$", re.IGNORECASE)


_DAYS = re.compile(r"^\d+day$", re.IGNORECASE)


def _availability(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """Stock from the delivery estimate, for the pass that never opens a product page.

    Only when nothing better is there. A product page states the answer outright and
    generic reads it; this fires on the cheap pass, whose card carries no stock word at all
    and whose listings were therefore all coming back `unknown` — a channel declaring it
    delivers availability and delivering none.
    """
    if fields.get("availability") not in (None, "unknown"):
        return {}
    code = str(payload.get("delivery_code") or "").strip()
    if _HOURS_OR_LESS.match(code):
        return {"availability": "in_stock"}
    if _DAYS.match(code):
        return {"availability": "preorder"}
    return {}


RULESET = register(
    SHOP,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="rdveikals-availability-from-delivery",
                layer=SHOP,
                why=(
                    "The cheap pass reads the listing card, which states how soon the shop"
                    " could hand the thing over and never states whether it has it. All"
                    " 1394 of its listings came back `unknown`, so the channel's"
                    " `delivers_quick` promised availability and delivered none. The"
                    " mapping is measured rather than guessed: on the product pages, where"
                    " the code and the shop's own word sit side by side, a code in minutes"
                    " or hours was `InStock` on 431 of 431, with no exception. A code in"
                    " days was `PreOrder` on 923 and `OutOfStock` on 40 — `10day` appears"
                    " as both — so the card genuinely cannot tell those two apart, and"
                    " reading days as `preorder` is wrong for 2.9% of this shop until the"
                    " full pass corrects them. That is the cheap pass being cheap, and it"
                    " is better stated than hidden behind `unknown`."
                ),
                body=_availability,
            ),
        ),
    ),
)
