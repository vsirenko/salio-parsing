"""Reading rdveikals.lv's laptops.

Apart from `rdveikals.py` for the reason `bigbox_laptops.py` is apart from `bigbox.py`: the
laptop rules import the laptop category, and a ruleset's fingerprint covers its imports.
"""

import re
from typing import Any

from app.features.offers.normalization.categories import laptops
from app.features.offers.normalization.rules import SOURCE, Rule, Ruleset, Vocabulary, register

# Laptops. The shop's specification table is the fullest of any here — on 24.09.2026 every
# one of its 1443 laptops carried a barcode, a colour, a keyboard layout, the memory, the
# drives and the screen — and the category's rules read those through the registry. What is
# this shop's is the processor, split over three fields (`Intel`, `Core Ultra 7`, `255H`),
# and the maker's part number, in a field of its own.
LAPTOPS_SLUG = "rdveikals-laptops"
LAPTOPS_VERSION = "rdveikals-laptops-2"
CPU_FIELDS = (
    "Procesors / Procesora ražotājs",
    "Procesors / Procesora sērija",
    "Procesors / Procesora modelis",
)
PART_NUMBER_FIELD = "Modeļa sērija / Modeļa nosaukums"
_REPEATED = re.compile(r"\b(\w+(?:\s+\w+){0,2})\s+\1\b", re.IGNORECASE)
# A part number is a code: letters and digits, no spaces. `Nav informācijas` — "no
# information" — is what the field says where the shop has none.
_PART_NUMBER = re.compile(r"^(?=[^\s]*\d)[A-Z0-9][A-Z0-9#./-]{4,}$", re.IGNORECASE)


def _cpu_from_three_fields(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The chip the three fields name together; where the title named another, neither."""
    specs = payload.get("specs") or {}
    stated = " ".join(str(specs.get(name) or "").strip() for name in CPU_FIELDS)
    # The model often repeats the series — `Ryzen 7` then `Ryzen 7 260`, `Ryzen AI 9 Pro` then
    # `Pro 375` — and a word said twice in a row is said once.
    stated = _REPEATED.sub(r"\1", stated)
    chips = laptops.processors(stated)
    if len(chips) != 1:
        return {}
    chip = chips.pop()
    identity = dict(fields.get("identity") or {})
    read = identity.get(laptops.CPU_KEY)
    # A coarser name gives way: the fields say `290HX` where the title says `290HX Plus`.
    if read == chip or (read and read.startswith(chip + " ")):
        return {}
    if read and chip.startswith(read + " "):
        return {"identity": {**identity, laptops.CPU_KEY: chip}}
    if read is None:
        return {"identity": {**identity, laptops.CPU_KEY: chip}}
    identity.pop(laptops.CPU_KEY)
    return {"identity": identity}


def _part_number(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    # `MDVT4KS/ A`: a space inside the code is the shop's, and `Nav informācijas` has no digit.
    stated = "".join(str((payload.get("specs") or {}).get(PART_NUMBER_FIELD) or "").split())
    return {"mpn": stated[:100]} if _PART_NUMBER.match(stated) else {}


LAPTOPS_RULESET = register(
    SOURCE,
    LAPTOPS_SLUG,
    Ruleset(
        version=LAPTOPS_VERSION,
        rules=(
            Rule(
                id="rdveikals-laptops-cpu-from-three-fields",
                layer=SOURCE,
                why=(
                    "The shop states the chip in three fields — maker, series, model: `Intel`,"
                    " `Core Ultra 7`, `255H`; `AMD`, `Ryzen 5`, `7520u` — and each alone names"
                    " nothing. Read together they are the category's spelling of the chip,"
                    " checked against what the title named; two chips leave the axis empty."
                ),
                body=_cpu_from_three_fields,
            ),
            Rule(
                id="rdveikals-laptops-part-number",
                layer=SOURCE,
                why=(
                    "`Modeļa nosaukums` is the maker's part number — `21MV00BEMX`, `B9ZY3ET`,"
                    " `NH.U05EP.008`, `MDVT4KS/A` — on 1414 of 1443 laptops, and"
                    " `Nav informācijas` on most of the rest. Another shop that sells the same"
                    " configuration writes the same code, so it goes to the part-number rung."
                ),
                body=_part_number,
            ),
        ),
    ),
)
