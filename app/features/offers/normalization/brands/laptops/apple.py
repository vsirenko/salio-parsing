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
VERSION = "apple-laptops-17"

_PART_NUMBER = re.compile(r"\b[A-Z0-9]{5}([A-Z]{2})/A\b")
# The code, to the layout the listings beside it named.
_LAYOUT = {"ZE": "english", "KS": "swedish"}
# What a shop calls the keyboard a code names, when it calls it something else.
_SAME_AS = {"swedish": ("nordic",)}


def _keyboard_from_the_part_number(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The layout the part number's code names; where a reading names another, neither —
    unless the other is only a shop's name for the same keyboard."""
    text = " ".join(str(fields.get(key) or "") for key in ("title", "mpn"))
    said = {_LAYOUT[code] for code in _PART_NUMBER.findall(text) if code in _LAYOUT}
    if len(said) != 1:
        return {}
    layout = said.pop()
    identity = dict(fields.get("identity") or {})
    read = identity.get(laptops.KEYBOARD_KEY)
    if read == layout:
        return {}
    # Apple makes no Nordic keyboard; the one it sells in the Nordic countries is `KS`, the
    # Swedish-Finnish layout, and euronics names that `NORDIC` on every MacBook it lists.
    # That is the shop's word for the same keyboard, not a disagreement.
    if read in _SAME_AS.get(layout, ()):
        return {"identity": {**identity, laptops.KEYBOARD_KEY: layout}}
    if read is None:
        return {"identity": {**identity, laptops.KEYBOARD_KEY: layout}}
    identity.pop(laptops.KEYBOARD_KEY)
    return {"identity": identity}


# A MacBook's name is its family: `MacBook Air`, `MacBook Pro`, `MacBook Neo`. The glass and
# the screen are axes of their own; bm writes it into the name
# without an inch mark — `MacBook Pro 16 Apple M4 Max …`, `MacBook Pro 14 M5 10 CPU` — and
# its MacBooks read as `MacBook Pro 16` where every other shop's read `MacBook Pro`.
_FAMILY = re.compile(r"^(MacBook\s+(?:Air|Pro|Neo))\b", re.IGNORECASE)


def _a_macbook_is_its_family(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    model = str(fields.get("model") or "").strip()
    found = _FAMILY.match(model)
    if found is None:
        return {}
    family = " ".join(
        w.capitalize() if w.lower() != "macbook" else "MacBook" for w in found.group(1).split()
    )
    return {"model": family} if family != model else {}


# The whole inch Apple names a MacBook by, to the diagonal it has. The Air's 13 was 13.3 on
# M1 and is 13.6 from M2; every other pair has been one screen since Apple silicon began.
_DIAGONAL = {("air", 13): 13.6, ("air", 15): 15.3, ("pro", 14): 14.2, ("pro", 16): 16.2}
_MACBOOK = re.compile(r"\bMacBook\s+(Air|Pro|Neo)\b", re.IGNORECASE)
# The size written bare straight after the family, `MacBook Air 15 M5 15.3`, for a listing
# whose screen was not read at all.
_BARE_SIZE = re.compile(r"^\s+(?:\(\d{4}\)\s+)?(\d{2}(?:\.\d)?)\b(?!\s?(?:GB|TB))", re.IGNORECASE)


def _the_screen_apple_gave_it(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The diagonal, where a listing gives the whole inch the MacBook is named by or leaves
    the screen out and the name says it bare: `MacBook Air 15 M5 15.3 16GB/512GB`."""
    title = str(fields.get("title") or "")
    found = _MACBOOK.search(title)
    if found is None:
        return {}
    identity = dict(fields.get("identity") or {})
    read = identity.get(laptops.SCREEN_KEY)
    if read is None:
        bare = _BARE_SIZE.match(title[found.end() :])
        if bare is None:
            return {}
        size = float(bare.group(1))
    else:
        size = float(read)
    cpu = str(identity.get(laptops.CPU_KEY) or "")
    exact = _DIAGONAL.get((found.group(1).lower(), int(size))) if size == int(size) else None
    if exact == 13.6 and cpu == "Apple M1":
        exact = 13.3
    if exact is not None and cpu.startswith("Apple M"):
        size = exact
    if size == read:
        return {}
    return {"identity": {**identity, laptops.SCREEN_KEY: size}}


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
            Rule(
                id="apple-laptops-a-macbook-is-its-family",
                layer=BRAND,
                why=(
                    "The name is the family; the glass and the size are axes. bm"
                    " writes the size into the name without an inch mark — `MacBook Pro 16"
                    " Apple M4 Max …`, `MacBook Pro 14 M5 10 CPU 10 GPU` — and 24.09.2026's"
                    " reading filed those as models no other shop's MacBook had."
                ),
                body=_a_macbook_is_its_family,
            ),
            Rule(
                id="apple-laptops-the-screen-apple-gave-it",
                layer=BRAND,
                why=(
                    "Apple names a MacBook by the whole inch and builds it a little larger:"
                    ' the Air `13"` is 13.6, the `15"` 15.3, the Pro\'s 14.2 and 16.2. On'
                    " 25.09.2026 the market read the Air at 13.0 on 33 listings and 13.6 on 71,"
                    " the Pro at 14.0 on 8 and 14.2 on 131 — one screen as two axes, so one"
                    " MacBook as two entries — and 24 Airs had none, discover writing it bare"
                    " after the name (`MacBook Air 15 M5 15.3`). Only on Apple silicon, and the"
                    " M1 Air's 13 is 13.3."
                ),
                body=_the_screen_apple_gave_it,
            ),
        ),
    ),
)
