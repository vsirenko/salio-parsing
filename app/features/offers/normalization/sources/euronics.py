"""Reading what euronics.lv's pages hand over.

Written against 319 real phones collected on 22.09.2026, and it is one rule — the shortest
ruleset here by a wide margin, because this shop states outright almost everything the
others have to be read for. Its product page gives the brand, the part number, the barcode
**and the model** as JSON-LD, so generic finds all four: 100%, 100%, 100% and 99.7%. No
other shop here states a model at all.

What is left is one word. The channel returns the shop's own stock wording, and `In stock`
happens to normalise itself — the generic reader lowercases it and finds `in_stock` in its
table. `On order` is this shop's phrasing for the other state and nothing knows it, so 58 of
319 read as `unknown` on a channel that declares it delivers availability.
"""

from typing import Any

from app.features.offers.normalization.rules import (
    SOURCE,
    Rule,
    Ruleset,
    Vocabulary,
    register,
)

SLUG = "euronics-phones"
VERSION = "euronics-1"

# The shop's two words, as the listing card prints them.
TO_ORDER = ("On order",)


def _availability(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    word = str(payload.get("availability") or "").strip()
    return {"availability": "preorder"} if word in TO_ORDER else {}


RULESET = register(
    SOURCE,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="euronics-on-order",
                layer=SOURCE,
                why=(
                    "`In stock` needs nothing: the generic reader lowercases it into"
                    " `in_stock`, which is already in its table, and 261 of 319 land"
                    " there by themselves. `On order` is the shop's word for the other"
                    " state and the table has never seen it, so the remaining 58 read as"
                    " `unknown` — a channel declaring it delivers availability and"
                    " delivering four fifths of it. The two words are the whole vocabulary"
                    " of this listing: every one of the 319 cards carries one or the other."
                    " Not read from the page's own JSON-LD, which says `InStock` for all"
                    " 319 including the 58 — the third shop in a row whose structured data"
                    " means the shop will sell the thing rather than that it has it."
                ),
                body=_availability,
            ),
        ),
    ),
)
