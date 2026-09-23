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
VERSION = "onea-5"

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


# Both sister shops title a tablet as they title a phone — `Planšetdators Apple iPad Air M4
# Wi-Fi MH334HC/A, 11", 12GB/128GB, …` — and on 23.09.2026 this rule read a model for 225
# of 1a's 229 tablets. ksenukai's own model rule reads its phones from a line field its
# tablets do not carry, and left `11` and `M4 11`; so both shops' tablets run this one.
TABLETS_SLUG = "onea-tablets"
TABLETS_VERSION = "onea-tablets-2"
KSENUKAI_TABLETS_SLUG = "ksenukai-tablets"
KSENUKAI_TABLETS_VERSION = "ksenukai-tablets-2"

# The codes the group leaves inside a tablet's head, by shape: Xiaomi's five-digit article
# (`Pad 8 71703`), Huawei's part number (`MatePad 53013UJQ`), Samsung's model code in full
# or short (`SM-X135FZAAEEE`, `Galaxy Tab S11 X730`), and a code that is letters, three or
# more digits and letters again (`TB390FU`, `ZAEG0022PL`). A name is not one of them: the
# same heads carry `Fun 1008`, `Viva H1003`, `MegaPad 2404v7` and `Iconia V11-21M`, and bigbox
# writes those names too.
_TABLET_CODE = re.compile(
    r"(?<!\S)(?:\d{5,}[A-Z]*|SM-[A-Z0-9]+|[A-Z]\d{3}|[A-Z]{2,}\d{3,}[A-Z]{2,})(?!\S)"
)
_SPACES = re.compile(r"\s{2,}")


def _tablet_model(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The phone cut, and then the codes the head still holds, wherever in it they sit."""
    model = _model(payload, fields, vocabulary).get("model")
    if not model:
        return {}
    model = _SPACES.sub(" ", _TABLET_CODE.sub("", model)).strip()
    return {"model": model} if model else {}


def _tablet_rules(prefix: str) -> tuple[Rule, ...]:
    return (
        Rule(
            id=f"{prefix}-tablets-model-from-title",
            layer=SOURCE,
            why=(
                "The sister shops' title order, cut as for 1a's phones: the head before the"
                " first comma, the maker's code off its end. The screen size after the comma"
                " is put back by the tablet category's rule. A tablet's head holds more codes"
                " than a phone's, and not only at the end: on 23.09.2026 38 of 458 tablets"
                " kept one (`Pad 8 71703`, `Galaxy Tab S11 X730`, `Yoga Tab Plus ZAEG0022PL`,"
                " `Galaxy Tab A11 SM-X135FZAAEEE Enterprise Edition`), and a model with a code"
                " in it agrees with no other shop — 17 of 1a's, with no barcode to fall back"
                " on, were unplaced for it."
            ),
            body=_tablet_model,
        ),
        Rule(
            id=f"{prefix}-tablets-color-from-title",
            layer=SOURCE,
            why="The group's fixed title end, `…, zila krās.`, as for its phones.",
            body=color_from_title,
        ),
    )


TABLETS_RULESET = register(
    SOURCE, TABLETS_SLUG, Ruleset(version=TABLETS_VERSION, rules=_tablet_rules("onea"))
)
KSENUKAI_TABLETS_RULESET = register(
    SOURCE,
    KSENUKAI_TABLETS_SLUG,
    Ruleset(version=KSENUKAI_TABLETS_VERSION, rules=_tablet_rules("ksenukai")),
)
