"""Reading what bm.market's GraphQL hands over.

Written against 937 real phones collected on 22.09.2026. Generic already finds the title,
the brand, the price, the barcode and the part number — the channel hands them over under
the names it looks for — so this module is the four things it cannot know: what the shop's
Latvian words for stock are worth, where the model ends, where the colour is when the
attribute block is missing, and that Apple's code is written into the name.
"""

import re
from typing import Any

from app.features.offers.normalization import colours, naming
from app.features.offers.normalization.rules import (
    SOURCE,
    Rule,
    Ruleset,
    Vocabulary,
    register,
)
from app.features.offers.normalization.shops.bm import APPLE_CODE

SLUG = "bm-phones"
VERSION = "bm-3"


# `256GB`, `1 TB`, `128 MB`. The name runs the configuration together with everything else
# and this is the only reliable boundary in it.
SIZE = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:TB|GB|MB)\b", re.IGNORECASE)
_EDGES = re.compile(r"^[\s,/|-]+|[\s,/|-]+$")


def _model(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The model, cut out of the name in front of the first capacity.

    The name is `BRAND MODEL RAM CAPACITY COLOUR` with no separator the shop keeps — some
    have a dash before the colour and some do not — so the capacity is the boundary and the
    brand comes off the front.
    """
    name = (payload.get("name") or "").strip()
    if not name:
        return {}

    head = naming.without_brand(name, payload.get("brand") or "")
    found = SIZE.search(head)
    if found:
        head = head[: found.start()]

    model = _EDGES.sub("", head)
    return {"model": model[:200]} if model else {}


def _color(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """Colour out of what follows the last capacity in the name.

    The last rather than the first, because the working memory is written the same way —
    `8GB 128GB Matte Charcoal` — and cutting at the first leaves the capacity on the front
    of the colour. Apple's code is taken off the end first; it is the only thing this shop
    puts after the colour.

    Everything is resolved through the registry, so a word the registry does not know
    produces nothing rather than a guess.
    """
    if not vocabulary.colours or (fields.get("identity") or {}).get("color"):
        return {}

    name = (payload.get("name") or "").strip()
    last = None
    for found in SIZE.finditer(name):
        last = found
    if last is None:
        return {}

    tail = _EDGES.sub("", APPLE_CODE.sub("", name[last.end() :]))
    canonical = colours.resolve(tail, vocabulary) if tail else None
    return {"identity": {**fields.get("identity", {}), "color": canonical}} if canonical else {}


RULESET = register(
    SOURCE,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="bm-model",
                layer=SOURCE,
                why=(
                    "Nothing in this shop states a model, so all 937 listings read without"
                    " one. The name is `BRAND MODEL RAM CAPACITY COLOUR` and the shop keeps"
                    " no separator — 422 of 937 put a dash before the colour and the rest do"
                    " not — so the first capacity is the only boundary in it. Measured: 937"
                    " of 937 yield a model, collapsing to 316 distinct, and none of them"
                    " carries a capacity through."
                ),
                body=_model,
            ),
            Rule(
                id="bm-colour",
                layer=SOURCE,
                why=(
                    "Only 476 of 937 carry the attribute block that holds `color`, and the"
                    " category's rules therefore find a colour on 454. The name has it for"
                    " most of the rest: what follows the **last** capacity, resolved through"
                    " the registry, brings the total to 844 (90.1%). The last rather than"
                    " the first because the working memory is written the same way —"
                    " `8GB 128GB Matte Charcoal` — and cutting at the first leaves `128GB`"
                    " on the front of the colour. What stays unread is a registry gap"
                    " (`Fog`, `Canyon`, `Lavander`) or one of the handful of names into"
                    " which the shop pasted a whole specification sheet, and both are better"
                    " left visible than guessed at."
                ),
                body=_color,
            ),
        ),
    ),
)
