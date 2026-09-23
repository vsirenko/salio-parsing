"""Apple, in tablets.

Apple sells five generations of iPad Pro at once, and a shop that writes `iPad Pro` has said
which of the lines it is and not which machine. bm.market does, on 39 of its 441 tablets on
23.09.2026, and discover and ksenukai on a handful: with every axis read, those listings
became catalogue entries named `iPad Pro`, `iPad Air` and `iPad` — 60 of them in one pass —
each of which would take an M1, an M2 and an M4 at the same capacity and colour as one
product. A name that leaves out the generation is not a model of an iPad.
"""

import re
from typing import Any

from app.features.offers.normalization.rules import BRAND, Rule, Ruleset, Vocabulary, register

CATEGORY = "tablets"
BRAND_KEY = "apple"
VERSION = "apple-tablets-1"

# What tells one iPad from the one before it, in the ways the shops write it, best first:
# the chip (`M4`, `A16`, `A17 Pro`), the generation (`10th Gen`, `7.Gen.`), the year Apple
# puts on the box (`(2022)`).
_CHIP = re.compile(r"\b[MA]\d{1,2}(?:\s+Pro)?\b")
_NTH = re.compile(r"\b\d{1,2}(?:st|nd|rd|th)?\.?\s*Gen(?:eration)?\b\.?", re.IGNORECASE)
# Only an iPad's years: `2048 x 2732` is a resolution.
_YEAR = re.compile(r"\(20[12]\d\)|\b20[12]\d\b")
_IPAD = re.compile(r"\biPad\b", re.IGNORECASE)


def _generation(text: str) -> str | None:
    for shape in (_CHIP, _NTH, _YEAR):
        found = shape.search(text)
        if found:
            return found.group().strip()
    return None


def _names_its_generation(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The model with the generation the title states, or no model when it states none."""
    title = str(fields.get("title") or "")
    model = str(fields.get("model") or "").strip()
    if not model or not _IPAD.search(model) or _generation(model):
        return {}
    stated = _generation(title)
    return {"model": f"{model} {stated}" if stated else ""}


RULESET = register(
    BRAND,
    (CATEGORY, BRAND_KEY),
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="apple-tablets-an-ipad-names-its-generation",
                layer=BRAND,
                why=(
                    "`iPad Pro` is five machines. 60 entries were made from models naming"
                    " the line and no generation — 37 `iPad Pro`, 15 `iPad`, 8 `iPad Air` —"
                    " each of which would have filed an M1 and an M4 of one capacity and"
                    " colour as one product. bm writes the generation after the capacity,"
                    " `… 2TB Silver (2022) MP273HC/A`, and the cut there took it off; where"
                    " the title states one it goes back on the model — the chip, else the"
                    " `10th Gen`, else the year. Where it states none there is no model: the"
                    " listing still matches by barcode or part number."
                ),
                body=_names_its_generation,
            ),
        ),
    ),
)
