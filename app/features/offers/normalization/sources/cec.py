"""Reading what shop.cec.lv's GraphQL hands over.

Written against 92 real phones collected on 22.09.2026. The channel hands the part number,
the model, the price and the stock flag over under the names generic looks for, so all four
arrive without help. One thing is missing and one thing is missing for good: the brand,
which this module supplies, and the barcode, which the shop does not have.
"""

import re
from typing import Any

from app.features.offers.normalization.rules import (
    SOURCE,
    Rule,
    Ruleset,
    Vocabulary,
    register,
)

SLUG = "cec-phones"
VERSION = "cec-3"

# What this channel collects, as the shop names the category it was resolved from.
CATEGORY = "iPhone"
BRAND = "Apple"


def _brand(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    if fields.get("brand_raw"):
        return {}
    return {"brand_raw": BRAND} if (payload.get("category") or "").strip() == CATEGORY else {}


RULESET = register(
    SOURCE,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="cec-brand",
                layer=SOURCE,
                why=(
                    "This shop states no brand anywhere. Its GraphQL schema has 41 fields on"
                    " a product and not one of them is a maker — no `manufacturer`, no"
                    " `brand`, no attribute standing in for either — so all 92 listings read"
                    " with none, and a listing with no brand cannot be matched or promoted."
                    " The category answers it: the shop is an Apple Premium Reseller and the"
                    " category resolved by path is `iPhone`. That is an inference, so it is"
                    " checked rather than assumed — 89 of these 92 part numbers are already"
                    " in this system, published by up to four other shops each, and every"
                    " one of them under Apple. The rule is tied to the category name and not"
                    " to the channel, because this shop also sells Bose, Sonos and"
                    " Bang & Olufsen, and a channel into one of those categories must not"
                    " inherit this answer."
                ),
                body=_brand,
            ),
        ),
    ),
)


# The iPads come through the same GraphQL, and the stated model is right for most — `iPad
# Air 13" M4` — and for the minis is the whole name: `iPad mini (A17 Pro) WiFi 256GB
# Purple`, which carries the capacity and the colour into the model and splits one iPad into
# one product per configuration.
TABLETS_SLUG = "cec-tablets"
TABLETS_VERSION = "cec-tablets-2"


def _ipad_brand(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    if fields.get("brand_raw"):
        return {}
    return {"brand_raw": BRAND} if (payload.get("category") or "").strip() == "iPad" else {}


_CAPACITY = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:TB|GB)\b", re.IGNORECASE)


def _model_before_the_capacity(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    model = str(fields.get("model") or "")
    found = _CAPACITY.search(model)
    if not found:
        return {}
    cut = model[: found.start()].strip(" ,-")
    return {"model": cut} if cut and cut != model else {}


TABLETS_RULESET = register(
    SOURCE,
    TABLETS_SLUG,
    Ruleset(
        version=TABLETS_VERSION,
        rules=(
            Rule(
                id="cec-tablets-brand",
                layer=SOURCE,
                why=(
                    "An Apple reseller that states no brand on its iPads either: without it"
                    " none of the 160 collected on 23.09.2026 resolved a maker, and none"
                    " could be placed."
                ),
                body=_ipad_brand,
            ),
            Rule(
                id="cec-tablets-model-before-the-capacity",
                layer=SOURCE,
                why=(
                    "The stated model of 18 of 160 iPad variants on 23.09.2026 is the whole"
                    " name, `iPad mini (A17 Pro) WiFi 256GB Purple`; cut at the capacity it"
                    " is the model the other 142 already state."
                ),
                body=_model_before_the_capacity,
            ),
        ),
    ),
)
