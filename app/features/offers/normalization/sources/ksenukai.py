"""Reading what ksenukai.lv's search index hands over.

Written against 520 real phones collected on 21.09.2026, not against a guess. Generic
already finds the title, the brand, the price, the category path and the stock flag in
this shape; what it cannot guess is where the barcode and the model are hidden, and what
looks like a part number and is not.
"""

import re
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
VERSION = "ksenukai-3"

# The shop's own article number. Every one of the 541 phones in the older corpus began
# `Y0000`, without exception.
INTERNAL_PREFIX = "Y0000"

# `…, 256 GB, melna krās.` — the shop closes a title with the colour and the word for
# it, and a two-tone case repeats the word: `melna krās./oranža krās.`. Anchored on the
# word rather than on the last comma for exactly that reason.
COLOUR = re.compile(r"([^,/]+?)\s+kr[āa]s\.?(?=\s*[/,]|\s*$)", re.IGNORECASE)


def _barcode(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    return {"gtin": barcodes.pick(payload.get("alternative_codes"))}


def _model(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    model = (payload.get("attributes") or {}).get("Modelis")
    return {"model": str(model).strip()[:200]} if model else {}


def color_from_title(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """Colour out of the one place this shop always puts it.

    Shared with `onea`, the group's other shop, which writes the same title: two copies
    of this would be two places to fix the day the group changes its wording.

    Not the loose "cut a colour out of a title" this project refuses elsewhere. The shape is
    fixed and the shop keeps it: the title ends with the colour and the Latvian word for
    colour, 487 times in 525. A case in two colours says the word twice —
    `melna krās./oranža krās.` — and the pair is its own value, because it is its own
    product with its own article number.

    Everything is resolved through the registry, so a word the registry does not know
    produces nothing rather than a guess. That is most of what this shop invents: `glacier`,
    `obsidian`, `cobalt violet` are a maker's marketing and stay unresolved on purpose.
    """
    if not vocabulary.colours:
        return {}
    title = str(payload.get("title_lv") or fields.get("title") or "")
    parts = [found.group(1).strip().casefold() for found in COLOUR.finditer(title)]
    if not parts:
        return {}

    named = [vocabulary.colours.get(part) for part in parts]
    if any(value is None for value in named):
        # Half a two-tone name is not a colour, and the half that resolved is the wrong
        # answer rather than a partial one.
        return {}

    canonical = "-".join(named)
    if canonical not in set(vocabulary.colours.values()):
        # `black-orange` exists as a value; an unseen pairing does not, and inventing one
        # here would put a value in a reading that the registry has never agreed to.
        return {}
    return {"identity": {**fields.get("identity", {}), "color": canonical}}


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
                id="ksenukai-color-from-title",
                layer=SOURCE,
                why=(
                    "This shop publishes no colour field, and colour is one of the two axes"
                    " a phone is told apart by — without it a model match between two of its"
                    " listings looks fully confirmed while nothing has compared the property"
                    " that differs. What it does have is a title that always ends the same"
                    " way: `…, 256 GB, melna krās.`, on 487 of 525. Reading a fixed position"
                    " is not the loose title-cutting this project refuses; the refusal is"
                    " about inventing a canonical value, and every word here is resolved"
                    " through the registry or dropped. Measured: 484 titles yield a word,"
                    " and what the registry knows resolves — the rest is the maker's"
                    " marketing (`glacier`, `obsidian`, `cobalt violet`) and stays"
                    " unresolved, which is the same decision `phones-color` makes."
                ),
                body=color_from_title,
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
