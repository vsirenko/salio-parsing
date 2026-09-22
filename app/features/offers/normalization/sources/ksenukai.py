"""Reading what ksenukai.lv's search index hands over.

Written against 520 real phones collected on 21.09.2026, not against a guess. Generic
already finds the title, the brand, the price, the category path and the stock flag in
this shape; what it cannot guess is where the barcode and the model are hidden, and what
looks like a part number and is not.
"""

from typing import Any

from app.features.offers.normalization import barcodes
from app.features.offers.normalization.rules import (
    FINISH,
    SOURCE,
    Rule,
    Ruleset,
    Vocabulary,
    register,
)

SLUG = "ksenukai-phones"
VERSION = "ksenukai-1"

# The shop's own article number. Every one of the 541 phones in the older corpus began
# `Y0000`, without exception.
INTERNAL_PREFIX = "Y0000"


def _barcode(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    return {"gtin": barcodes.pick(payload.get("alternative_codes"))}


def _model(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    model = (payload.get("attributes") or {}).get("Modelis")
    return {"model": str(model).strip()[:200]} if model else {}


def _not_a_part_number(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    mpn = fields.get("mpn")
    if mpn and str(mpn).startswith(INTERNAL_PREFIX):
        return {"mpn": None}
    return {}


RULESET = register(
    SOURCE,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="ksenukai-barcode",
                layer=SOURCE,
                why=(
                    "The barcode is in `alternative_codes` with three other numbers and no"
                    " label: the shop's product code, its article number, and the EAN with"
                    " its check digit lopped off. Generic looks for a field called `ean` or"
                    " `barcode` and finds neither, so without this the strongest signal the"
                    " matcher has is invisible on every one of these products."
                ),
                body=_barcode,
            ),
            Rule(
                id="ksenukai-model",
                layer=SOURCE,
                why=(
                    "`Modelis` is on 100% of these products, and it is in the index's"
                    " base64-keyed columns rather than in the list it calls `attributes` —"
                    " so it reaches us inside the attribute table, where generic has no"
                    " reason to look. It is what brand-and-model matching stands on."
                ),
                body=_model,
            ),
            Rule(
                id="ksenukai-article-is-not-a-part-number",
                layer=FINISH,
                why=(
                    "All 541 phones in the older corpus had an article number beginning"
                    " `Y0000`: Kesko's own sequence, which no other shop can ever agree"
                    " with. The previous system filed it as the part number and reported"
                    " 100% MPN coverage for this shop — a number that described nothing."
                    " A real manufacturer code is in the title on about 13% of them"
                    " (`Samsung Galaxy A57 5G SM-A576BLB`), which is work for a brand rule,"
                    " not for this one."
                ),
                body=_not_a_part_number,
            ),
        ),
    ),
)
