"""Reading what bm.market's GraphQL hands over.

Written against 937 real phones collected on 22.09.2026. Generic already finds the title,
the brand, the price, the barcode and the part number — the channel hands them over under
the names it looks for — so this module is the four things it cannot know: what the shop's
Latvian words for stock are worth, where the model ends, where the colour is when the
attribute block is missing, and that Apple's code is written into the name.
"""

import re
from typing import Any

from app.features.offers.normalization import colours
from app.features.offers.normalization.rules import (
    SOURCE,
    Rule,
    Ruleset,
    Vocabulary,
    register,
)

SLUG = "bm-phones"
VERSION = "bm-1"

# The shop's own words. It is a showroom that orders in, so `Pēc pasūtījuma` is its ordinary
# state rather than an exception.
IN_STOCK = ("Ir veikalā",)
TO_ORDER = ("Pēc pasūtījuma",)

# `256GB`, `1 TB`, `128 MB`. The name runs the configuration together with everything else
# and this is the only reliable boundary in it.
SIZE = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:TB|GB|MB)\b", re.IGNORECASE)
# Apple's own code, as this shop appends it: `… Cosmic Orange MG8M4`. Upper case, four to
# six characters, at the very end.
APPLE_CODE = re.compile(r"\s([A-Z][A-Z0-9]{3,5})$")
APPLE = "apple"
_EDGES = re.compile(r"^[\s,/|-]+|[\s,/|-]+$")


def _availability(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    word = str(payload.get("availability") or "").strip()
    if word in IN_STOCK:
        return {"availability": "in_stock"}
    if word in TO_ORDER:
        return {"availability": "preorder"}
    return {}


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

    brand = (payload.get("brand") or "").strip()
    head = name[len(brand) :] if brand and name.casefold().startswith(brand.casefold()) else name
    found = SIZE.search(head)
    if found:
        head = head[: found.start()]

    model = _EDGES.sub("", head)
    return {"model": model[:200]} if model else {}


def _part_number(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """Apple's code, which this shop writes into the name when it has no `mpn` field.

    Only for Apple, and only when the field is empty. Both halves are the measurement: the
    two sets never overlap on these 937, and the same pattern applied to the other brands
    matched twice and was wrong both times.
    """
    if fields.get("mpn"):
        return {}
    if (payload.get("brand") or "").strip().casefold() != APPLE:
        return {}
    found = APPLE_CODE.search((payload.get("name") or "").strip())
    return {"mpn": found.group(1)} if found else {}


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
                id="bm-availability",
                layer=SOURCE,
                why=(
                    "The record's `stock_status` reads `IN_STOCK` on 936 of 937, which is"
                    " Magento saying the shop will sell the thing rather than that it has"
                    " it. The shop states what it means in `availability_type` beside it:"
                    " 934 `Pēc pasūtījuma` and 3 `Ir veikalā`. This is a showroom that"
                    " orders in, so to-order is its ordinary state and reading the flag"
                    " instead would report a warehouse that does not exist."
                ),
                body=_availability,
            ),
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
                id="bm-apple-part-number",
                layer=SOURCE,
                why=(
                    "Apple is where this shop is thinnest — 42 barcodes on 196 products,"
                    " against 74% for Xiaomi — and its part number is missing on 155 of"
                    " them. It is not missing from the page: the shop appends Apple's own"
                    " code to the name, `iPhone 17 Pro 512GB Cosmic Orange MG8M4`, on 120 of"
                    " those 155. The two are never both present, which is what says the shop"
                    " writes the code in one place or the other, so reading the name where"
                    " the field is empty takes Apple from 41 part numbers to 161 (82.1%)."
                    " Restricted to Apple on purpose: the same pattern over the other 741"
                    " products matched twice and was part of the model both times"
                    " (`Emporia FN313`)."
                ),
                body=_part_number,
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
