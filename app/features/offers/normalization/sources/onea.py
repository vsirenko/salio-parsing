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
from app.features.offers.normalization.shops.onea import _PART_NUMBER, _head
from app.features.offers.normalization.sources.ksenukai import color_from_title

SLUG = "onea-phones"
VERSION = "onea-3"

_TRAILING = re.compile(r"[\s,/-]+$")


def _model(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """What is left of the head once the maker's code is off the end of it."""
    title = str(payload.get("title_lv") or fields.get("title") or "")
    head = _head(title, (fields.get("brand_raw") or "").strip(), vocabulary)
    model = _TRAILING.sub("", _PART_NUMBER.sub("", head)).strip()
    return {"model": model[:200]} if model else {}


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
