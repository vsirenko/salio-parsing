"""Reading bigbox.lv's laptops.

A module of its own rather than a third ruleset in `bigbox.py`: a ruleset's fingerprint is
its module and what the module imports, and the laptop rules import the laptop category.
Kept beside the phones, every change to how a laptop is read would have moved the phones'
version and recomputed their readings for nothing.
"""

import re
from typing import Any

from app.features.offers.normalization.categories import laptops
from app.features.offers.normalization.rules import SOURCE, Rule, Ruleset, Vocabulary, register

# Laptops. The category's rules read the configuration; what is this shop's is where it
# puts the keyboard. On 24.09.2026, over its 2184 new laptops: in a field the index names
# nothing, `attribute_string_1171` (`vācu`, `EN`, `SWE`, `RU`), on 411; and in the titles one
# distributor writes, as a code just before the operating system — `… 512 SSD EN W11P` — on
# 127 (`EN` 99, `NOR` 21, `LV` 4, `DE` 3).
LAPTOPS_SLUG = "bigbox-laptops"
LAPTOPS_VERSION = "bigbox-laptops-10"
KEYBOARD_FIELD = "attribute_string_1171"
_BEFORE_THE_SYSTEM = re.compile(
    r"\b([A-Z]{2,3})\s+(?:W1[01]\w*|Win\s?1[01]\w*|NoOS|FreeDOS|DOS|Linux)\b"
)


def _keyboard(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The layout from the unnamed field and the code before the system; one, or none."""
    words = [str((payload.get("attributes") or {}).get(KEYBOARD_FIELD) or "")]
    words += _BEFORE_THE_SYSTEM.findall(str(fields.get("title") or ""))
    said = {m for word in words if word and (m := laptops.keyboard_word(vocabulary, word))}
    identity = dict(fields.get("identity") or {})
    already = identity.pop(laptops.KEYBOARD_KEY, None)
    if not said:
        return {}
    if already is not None:
        said.add(already)
    if len(said) != 1:
        return {"identity": identity}
    return {"identity": {**identity, laptops.KEYBOARD_KEY: said.pop()}}


LAPTOPS_RULESET = register(
    SOURCE,
    LAPTOPS_SLUG,
    Ruleset(
        version=LAPTOPS_VERSION,
        rules=(
            Rule(
                id="bigbox-laptops-keyboard",
                layer=SOURCE,
                why=(
                    "This shop's two places for a layout, measured on 24.09.2026 over 2184"
                    " new laptops: its unnamed field `attribute_string_1171` on 411, and a"
                    " code in front of the operating system in one distributor's titles —"
                    " `… 512 SSD EN W11P` — on 127. The words go through the registry like"
                    " any other shop's; what is this shop's is where they stand. A layout"
                    " the category already read and one of these that disagrees leave the"
                    " axis empty."
                ),
                body=_keyboard,
            ),
        ),
    ),
)
