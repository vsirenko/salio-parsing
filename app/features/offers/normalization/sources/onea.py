"""Reading what 1a.lv's search index hands over.

Written against 443 real phones collected on 22.09.2026. The group's other shop publishes
the same record through the same engine, so most of this is ksenukai's reading reused. What
is not reused is here because this index is a strict subset of that one: **no barcodes at
all**, and no `Modelis` column. That takes away the rung that is proof and the field the
model was read from, and leaves the title — which, happily, this group writes to a fixed
shape:

    Mobilais telefons Samsung Galaxy S26 Ultra 5G SM-S948BZKDEUE, 256 GB, melna krās.
    [ kind          ] [brand] [ model             ] [part no.  ]  [size]  [colour]
"""

import re
from typing import Any

from app.features.offers.normalization.rules import SOURCE, Rule, Ruleset, Vocabulary, register
from app.features.offers.normalization.sources.ksenukai import color_from_title

SLUG = "onea-phones"
VERSION = "onea-1"

# `SM-S948BZKDEUE`, `MZB0MY8EU`, `MTP03PX/A`. A maker's own code: letters and digits with no
# spaces, long enough not to be a word, and at the end of the part of the title before the
# first comma. Apple's ends `/A`, which the brand layer reads further.
# The hyphenated form comes first on purpose: `SM-S948BZKDEUE` read without it loses the
# `SM-`, because the tail alone is already long enough to look like a whole code.
_PART_NUMBER = re.compile(r"\s*\b([A-Z]{2,4}-[A-Z0-9]{4,}|[A-Z0-9]{5,7}/A|[A-Z][A-Z0-9]{5,})\s*$")
_TRAILING = re.compile(r"[\s,/-]+$")


def _head(title: str, brand: str, vocabulary: Vocabulary) -> str:
    """The part of the title before the size, with the kind and the brand taken off."""
    words = title.split(",", 1)[0].split()
    at = 0
    while at < len(words) and words[at].strip(",.").casefold() in vocabulary.category_names:
        at += 1
    if brand and at < len(words) and words[at].casefold() == brand.casefold():
        at += 1
    return " ".join(words[at:])


def _model(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """What is left of the head once the maker's code is off the end of it."""
    title = str(payload.get("title_lv") or fields.get("title") or "")
    head = _head(title, (fields.get("brand_raw") or "").strip(), vocabulary)
    model = _TRAILING.sub("", _PART_NUMBER.sub("", head)).strip()
    return {"model": model[:200]} if model else {}


def _part_number(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    title = str(payload.get("title_lv") or fields.get("title") or "")
    found = _PART_NUMBER.search(_head(title, (fields.get("brand_raw") or "").strip(), vocabulary))
    return {"mpn": found.group(1)[:100]} if found else {}


RULESET = register(
    SOURCE,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="onea-model-from-title",
                layer=SOURCE,
                why=(
                    "This index has no `Modelis` column — the sister shop's does, and that"
                    " is where its model comes from on 100% of products. Here the title is"
                    " the only source, and the group writes it to one shape: the kind of"
                    " thing, the brand, the model, the maker's code, then a comma and the"
                    " configuration. The kind comes off using the words in the category"
                    " registry rather than a list in this module, because they are Latvian."
                ),
                body=_model,
            ),
            Rule(
                id="onea-part-number-from-title",
                layer=SOURCE,
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
            Rule(
                id="onea-color-from-title",
                layer=SOURCE,
                why=(
                    "The same title and the same rule as the sister shop: the colour and the"
                    " Latvian word for it close every title, on 406 of 443. It matters more"
                    " here — with no barcode, a model match is all this shop has, and"
                    " without colour that match cannot be trusted enough to carry anything."
                    " 264 resolve through the registry today; the rest are the maker's"
                    " marketing and stay unresolved, which is the same decision made"
                    " everywhere else."
                ),
                body=color_from_title,
            ),
        ),
    ),
)
