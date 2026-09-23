"""onea: what its codes and stock words mean, in every category it sells.

Moved out of `sources/onea.py` on 23.09.2026, when a second category made the
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

SLUG = "onea"
VERSION = "onea-shop-1"


# `SM-S948BZKDEUE`, `MZB0MY8EU`, `MTP03PX/A`. A maker's own code: letters and digits with no
# spaces, long enough not to be a word, and at the end of the part of the title before the
# first comma. Apple's ends `/A`, which the brand layer reads further.
# The hyphenated form comes first on purpose: `SM-S948BZKDEUE` read without it loses the
# `SM-`, because the tail alone is already long enough to look like a whole code.
_PART_NUMBER = re.compile(r"\s*\b([A-Z]{2,4}-[A-Z0-9]{4,}|[A-Z0-9]{5,7}/A|[A-Z][A-Z0-9]{5,})\s*$")


def _head(title: str, brand: str, vocabulary: Vocabulary) -> str:
    """The part of the title before the size, with the kind and the brand taken off."""
    words = title.split(",", 1)[0].split()
    at = 0
    while at < len(words) and words[at].strip(",.").casefold() in vocabulary.category_names:
        at += 1
    if brand and at < len(words) and words[at].casefold() == brand.casefold():
        at += 1
    return " ".join(words[at:])


def _part_number(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    title = str(payload.get("title_lv") or fields.get("title") or "")
    found = _PART_NUMBER.search(_head(title, (fields.get("brand_raw") or "").strip(), vocabulary))
    return {"mpn": found.group(1)[:100]} if found else {}


RULESET = register(
    SHOP,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="onea-part-number-from-title",
                layer=SHOP,
                why=(
                    "The rung this shop lives on. It publishes no barcode at all, so the"
                    " strongest signal the matcher has is missing from every one of its 443"
                    " products, and a model string alone is a family rather than a thing to"
                    " buy. The maker's own code is in 43.8% of the titles —"
                    " `SM-S948BZKDEUE`, `MTP03PX/A`, `MZB0MY8EU` — and unlike the shop's"
                    " `Y0000…` article number it is a code another shop can agree with."
                    " Apple's shape is read further by the brand layer."
                ),
                body=_part_number,
            ),
        ),
    ),
)
