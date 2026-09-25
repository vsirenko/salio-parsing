"""Reading discover.lv's laptops.

Apart from `discover.py` because a rule here imports the laptop category, and a ruleset's
fingerprint covers what its module imports. Written against the 31 of 25.09.2026, 30 of them
MacBooks, out of the same export the phones and the tablets come from.
"""

import re
from typing import Any

from app.features.offers.normalization.categories import laptops
from app.features.offers.normalization.rules import SOURCE, Rule, Ruleset, Vocabulary, register

LAPTOPS_SLUG = "discover-laptops"
LAPTOPS_VERSION = "discover-laptops-5"

# Apple's whole part number, region and all: `MDVT4ZE/A`. The five-character stem the shop
# writes on older ones — `(MR7K3)` — names no one configuration and is left alone.
_APPLE_PART = re.compile(r"^[A-Z0-9]{5}[A-Z]{2}/A$")
# The keyboard, twice: the two-letter code and the three-letter one, `EN ENG`, `RU RUS`.
_LAYOUT_PAIR = re.compile(r"\b([A-Z]{2})\s([A-Z]{3})\b")


def _part_number_from_the_brackets(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    line = str(payload.get("line") or "")
    if fields.get("mpn") or not _APPLE_PART.match(line):
        return {}
    return {"mpn": line}


def _keyboard_written_twice(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    said = set()
    for short, long in _LAYOUT_PAIR.findall(str(fields.get("title") or "")):
        one, other = (
            laptops.keyboard_word(vocabulary, short),
            laptops.keyboard_word(vocabulary, long),
        )
        if one is not None and one == other:
            said.add(one)
    if len(said) != 1:
        return {}
    layout = said.pop()
    identity = dict(fields.get("identity") or {})
    if identity.get(laptops.KEYBOARD_KEY) in (None, layout):
        return {"identity": {**identity, laptops.KEYBOARD_KEY: layout}}
    identity.pop(laptops.KEYBOARD_KEY)
    return {"identity": identity}


LAPTOPS_RULESET = register(
    SOURCE,
    LAPTOPS_SLUG,
    Ruleset(
        version=LAPTOPS_VERSION,
        rules=(
            Rule(
                id="discover-laptops-part-number-from-the-brackets",
                layer=SOURCE,
                why=(
                    "On a phone the code in brackets is a family — `(SM-S948B)` covers every"
                    " colour — and the channel hands it over as a line. On a MacBook it is"
                    " Apple's part number for one configuration: 17 of the 31 of 25.09.2026"
                    " end `(MDVT4ZE/A)`, the same string cec and bigbox publish as theirs."
                    " Only the whole number, region included."
                ),
                body=_part_number_from_the_brackets,
            ),
            Rule(
                id="discover-laptops-keyboard-written-twice",
                layer=SOURCE,
                why=(
                    "The keyboard is written as a pair of codes with no marker — `EN ENG` on"
                    " 16 of the 31, `RU RUS` on 9 — and no marker means the category's rule"
                    " does not read it. Both halves have to name one layout, through the"
                    " registry's words."
                ),
                body=_keyboard_written_twice,
            ),
        ),
    ),
)
