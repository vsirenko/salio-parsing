"""Apple, in laptops.

Apple writes a MacBook's keyboard into its part number: `MDH74ZE/A` and `MDH74KS/A` are one
MacBook Air with two keyboards, and the two letters before `/A` say which. bigbox's titles
name the layout beside it on the same listings, and on 24.09.2026 they agreed every time:
`KS` with `SWE` on 53, `ZE` with `INT` on 38. Only those two codes are read — they are the
ones measured, and Apple has a dozen more.
"""

import re
from typing import Any

from app.features.offers.normalization.categories import laptops
from app.features.offers.normalization.rules import BRAND, Rule, Ruleset, Vocabulary, register

CATEGORY = "laptops"
BRAND_KEY = "apple"
VERSION = "apple-laptops-3"

_PART_NUMBER = re.compile(r"\b[A-Z0-9]{5}([A-Z]{2})/A\b")
# The code, to the layout the listings beside it named.
_LAYOUT = {"ZE": "english", "KS": "swedish"}


def _keyboard_from_the_part_number(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The layout the part number's code names; where a reading names another, neither."""
    text = " ".join(str(fields.get(key) or "") for key in ("title", "mpn"))
    said = {_LAYOUT[code] for code in _PART_NUMBER.findall(text) if code in _LAYOUT}
    if len(said) != 1:
        return {}
    layout = said.pop()
    identity = dict(fields.get("identity") or {})
    read = identity.get(laptops.KEYBOARD_KEY)
    if read == layout:
        return {}
    if read is None:
        return {"identity": {**identity, laptops.KEYBOARD_KEY: layout}}
    identity.pop(laptops.KEYBOARD_KEY)
    return {"identity": identity}


RULESET = register(
    BRAND,
    (CATEGORY, BRAND_KEY),
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="apple-laptops-keyboard-from-the-part-number",
                layer=BRAND,
                why=(
                    "`MDH74ZE/A` and `MDH74KS/A` are one MacBook Air with two keyboards. On"
                    " bigbox's titles of 24.09.2026 the code and the layout written beside it"
                    " agreed every time — `KS` with `SWE` on 53, `ZE` with `INT` on 38 — so"
                    " the code gives the layout where nothing else did. Only the two measured"
                    " codes are read."
                ),
                body=_keyboard_from_the_part_number,
            ),
        ),
    ),
)
