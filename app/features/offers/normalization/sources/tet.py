"""Reading what tet.lv's pages hand over.

Written against 319 real phones collected on 22.09.2026. This shop states more on its
listing than any other here — the part number is on the card — and its product page states
the barcode, so generic finds the title, the brand, the barcode, the part number and the
price without help, and the category's rules find the colour and the capacity in its
specification table. Two things are left: where the model ends, and what an absent flag
means.
"""

import re
from typing import Any

from app.features.offers.normalization import naming
from app.features.offers.normalization.rules import (
    SOURCE,
    Rule,
    Ruleset,
    Vocabulary,
    register,
)

SLUG = "tet-phones"
VERSION = "tet-1"

# `256GB`, `1 TB`. The usual way this shop writes the configuration.
SIZE = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:TB|GB|MB)\b", re.IGNORECASE)
# `8+256`, `12+512` — the other way, with no unit at all, which 58 of the 319 use.
PLUS = re.compile(r"\b\d{1,2}\s*\+\s*\d{2,4}\b")
_EDGES = re.compile(r"^[\s,/|+-]+|[\s,/|+-]+$")

# The shop's flag for a product it has not got yet. Nothing at all is the other state.
SOON = "Drīzumā"


def _availability(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    flag = str(payload.get("availability") or "").strip()
    return {"availability": "preorder" if flag == SOON else "in_stock"}


def _model(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The model, cut out of the name in front of the configuration.

    Whichever way the configuration is written: this shop uses both `256GB` and `8+256`, and
    the second one carries no unit for a capacity regex to find.
    """
    name = (payload.get("name") or "").strip()
    if not name:
        return {}

    head = naming.without_brand(name, payload.get("brand") or "")
    found = SIZE.search(head) or PLUS.search(head)
    if found:
        head = head[: found.start()]

    model = _EDGES.sub("", head).strip()
    return {"model": model[:200]} if model else {}


RULESET = register(
    SOURCE,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="tet-availability",
                layer=SOURCE,
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
            Rule(
                id="tet-model",
                layer=SOURCE,
                why=(
                    "Nothing in this shop states a model as such — its specification table"
                    " has `Sērija / modelis`, but that reads `Apple iPhone 18 Pro`, the"
                    " family with the brand on it, and it is on the page rather than the"
                    " card. The name is the usual `BRAND MODEL CONFIGURATION COLOUR`, so the"
                    " brand comes off and the configuration is the cut. It is written two"
                    " ways: 261 of the 319 use `256GB` and the other 58 use `8+256`, with no"
                    " unit for a capacity regex to find. Reading only the first leaves"
                    " `M8 5G 8+256 Black` as a model, which is one product per colour and"
                    " per configuration; reading both gives 126 distinct models where the"
                    " first alone gave 146."
                ),
                body=_model,
            ),
        ),
    ),
)
