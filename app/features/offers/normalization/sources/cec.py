"""Reading what shop.cec.lv's GraphQL hands over.

Written against 92 real phones collected on 22.09.2026. The channel hands the part number,
the model, the price and the stock flag over under the names generic looks for, so all four
arrive without help. One thing is missing and one thing is missing for good: the brand,
which this module supplies, and the barcode, which the shop does not have.
"""

from typing import Any

from app.features.offers.normalization.rules import (
    SOURCE,
    Rule,
    Ruleset,
    Vocabulary,
    register,
)

SLUG = "cec-phones"
VERSION = "cec-1"

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
