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
VERSION = "tet-4"

# `256GB`, `1 TB`. The usual way this shop writes the configuration.
SIZE = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:TB|GB|MB)\b", re.IGNORECASE)
# `12+256GB`, `8+256` — the other way, memory and capacity joined by a plus, with the unit
# on the end or missing altogether. 189 of the 319 write it with the unit and 26 without.
PLUS = re.compile(r"\b\d{1,2}\s*\+\s*\d{2,4}(?:\s?(?:TB|GB|MB))?\b", re.IGNORECASE)
# A `+` at the end is left where a letter or a digit holds it: `Galaxy Tab S10 FE+ 8+128GB`
# is the FE+, and taking the plus with the separators read it as the FE, which is another
# tablet.
_EDGES = re.compile(r"^[\s,/|+-]+|(?:[\s,/|-]|(?<![A-Za-z0-9])\+)+$")


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
    # The earliest of the two, not the first one tried. On `F7 12+256GB` the capacity
    # pattern matches `256GB`, which is inside the configuration rather than the start of
    # it, and cutting there leaves `F7 12+` — the working memory, on the model.
    found = [match for match in (SIZE.search(head), PLUS.search(head)) if match]
    if found:
        head = head[: min(found, key=lambda match: match.start()).start()]

    model = _EDGES.sub("", head).strip()
    return {"model": model[:200]} if model else {}


RULESET = register(
    SOURCE,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="tet-model",
                layer=SOURCE,
                why=(
                    "Nothing in this shop states a model as such — its specification table"
                    " has `Sērija / modelis`, but that reads `Apple iPhone 18 Pro`, the"
                    " family with the brand on it, and it is on the page rather than the"
                    " card. The name is the usual `BRAND MODEL CONFIGURATION COLOUR`, so the"
                    " brand comes off and the configuration is the cut. It is written two"
                    " ways, and the second one is the majority: 189 of the 319 write"
                    " `12+256GB` and 26 write `8+256`, against 104 that write a plain"
                    " `256GB`. Both have to be read, and the **earliest** of the two"
                    " matches is the cut — the capacity pattern finds `256GB` inside"
                    " `12+256GB`, which is the middle of the configuration rather than its"
                    " start, and cutting there leaves `Galaxy S26 FE 8` and `Galaxy S25 12`:"
                    " one entry per memory size. Reading only the plain form gave 146"
                    " distinct models, reading both but cutting at the wrong one gave 126,"
                    " and cutting at the earliest gives 117."
                ),
                body=_model,
            ),
        ),
    ),
)


# The tablets are the same pages under `Planšetdatori`, and their names keep the phones'
# shape — `Samsung Galaxy Tab S10 FE+ 8+128GB 5G Gray`, `Apple iPad 11" (A16) Wi-Fi 128GB -
# Silver` — so the phones' cut reads them; the screen and the radio words that stay on an
# iPad's head are the tablet category's to take off. 205 of 210 carry a barcode.
TABLETS_SLUG = "tet-tablets"
TABLETS_VERSION = "tet-tablets-1"

TABLETS_RULESET = register(
    SOURCE,
    TABLETS_SLUG,
    Ruleset(
        version=TABLETS_VERSION,
        rules=(
            Rule(
                id="tet-tablets-model",
                layer=SOURCE,
                why=(
                    "No model is stated for a tablet either, and the name is the phones'"
                    " shape, both ways of writing the configuration included: the phones'"
                    " cut gives a model for 210 of 210 collected on 23.09.2026."
                ),
                body=_model,
            ),
        ),
    ),
)
