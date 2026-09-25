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
VERSION = "apple-tablets-3"

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


# A shop's processor field, when it names Apple's chip and nothing else: `Apple A17 Pro`.
_CHIP_FIELD = re.compile(r"^\s*Apple\s+([MA]\d{1,2}(?:\s+Pro)?)\s*$", re.IGNORECASE)


def _chip_in_the_fields(fields: dict[str, Any]) -> str | None:
    found = {
        match.group(1)
        for value in (fields.get("attributes") or {}).values()
        if (match := _CHIP_FIELD.match(str(value)))
    }
    return found.pop() if len(found) == 1 else None


def _names_its_generation(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The model with the generation the title states — else the chip a field names — or no
    model when neither does."""
    title = str(fields.get("title") or "")
    model = str(fields.get("model") or "").strip()
    if not model or not _IPAD.search(model) or _generation(model):
        return {}
    stated = _generation(title) or _chip_in_the_fields(fields)
    return {"model": f"{model} {stated}" if stated else ""}


# An iPad is named by its line and its chip, the way Apple names the ones it sells now —
# `iPad Air (M3)`, `iPad (A16)`, `iPad mini (A17 Pro)` — without the brackets, as the
# catalogue already wrote the lines that held 1400 of 1560 listings on 25.09.2026. The
# older generations arrived under their generation or their year instead, `iPad 10th Gen`,
# `iPad Air (2022)`, `iPad Pro (2022)`, and each spelling was a family of its own. These are
# Apple's, fixed history: which chip each generation and each year carried.
_LINE = re.compile(r"^\s*iPad(?:\s+(Air|Pro|mini))?\b", re.IGNORECASE)
_BY_GENERATION = {
    ("iPad", 9): "A13",
    ("iPad", 10): "A14",
    ("iPad", 11): "A16",
    ("iPad Air", 4): "A14",
    ("iPad Air", 5): "M1",
    ("iPad Air", 6): "M2",
    ("iPad Air", 7): "M3",
    ("iPad Air", 8): "M4",
    # The Pro's generations are numbered per size — the 11-inch's 4th and the 12.9-inch's
    # 4th are different chips — so only the 12.9-inch 6th, which nothing else shares.
    ("iPad Pro", 6): "M2",
    ("iPad mini", 6): "A15",
    ("iPad mini", 7): "A17 Pro",
}
_BY_YEAR = {
    ("iPad", 2021): "A13",
    ("iPad", 2022): "A14",
    ("iPad", 2025): "A16",
    ("iPad Air", 2020): "A14",
    ("iPad Air", 2022): "M1",
    ("iPad Air", 2024): "M2",
    ("iPad Air", 2025): "M3",
    ("iPad Air", 2026): "M4",
    ("iPad Pro", 2021): "M1",
    ("iPad Pro", 2022): "M2",
    ("iPad Pro", 2024): "M4",
    ("iPad Pro", 2025): "M5",
    ("iPad mini", 2021): "A15",
    ("iPad mini", 2024): "A17 Pro",
}
_NUMBER = re.compile(r"\d{1,2}")


def _chip_of(line: str, text: str) -> str | None:
    found = _CHIP.search(text)
    if found:
        chip = " ".join(found.group().split())
        return chip[0].upper() + chip[1:]
    nth = _NTH.search(text)
    if nth and (chip := _BY_GENERATION.get((line, int(_NUMBER.search(nth.group()).group())))):
        return chip
    year = _YEAR.search(text)
    if year:
        return _BY_YEAR.get((line, int(year.group().strip("()"))))
    return None


def _named_by_its_chip(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """`iPad 10th Gen` -> `iPad A14`, `Ipad Mini (A17 Pro)` -> `iPad mini A17 Pro`.

    The chip the model names, else the one its generation or its year carried; a model that
    gives neither is left as it is. The glass is not this rule's: the category puts
    `Nano-texture` back on after it, from the title."""
    model = str(fields.get("model") or "").strip()
    found = _LINE.match(model)
    if found is None:
        return {}
    line = "iPad" + (f" {found.group(1).capitalize()}" if found.group(1) else "")
    line = line.replace("Mini", "mini")
    rest = model[found.end() :]
    chip = (
        _chip_of(line, rest)
        or _chip_of(line, str(fields.get("title") or ""))
        or _chip_in_the_fields(fields)
    )
    if chip is None:
        return {}
    named = f"{line} {chip}"
    return {"model": named} if named != model else {}


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
                    " `10th Gen`, else the year. bigbox's `iPad mini 5G TD-LTE un FDD-LTE"
                    " 256 GB` names none, and its `Procesors` field says `Apple A17 Pro`: a"
                    " field that is only Apple's chip gives it. Where nothing states one there"
                    " is no model: the listing still matches by barcode or part number."
                ),
                body=_names_its_generation,
            ),
            Rule(
                id="apple-tablets-an-ipad-is-named-by-its-chip",
                layer=BRAND,
                why=(
                    "Twenty iPad families on 25.09.2026, nine of them holding 1400 of the"
                    " 1560 listings under the line and the chip — `iPad Air M4`, `iPad Pro"
                    " M5` — and eleven holding the rest under a generation or a year:"
                    " `iPad 10th Gen` (17), `iPad Pro (2022)` (37), `iPad Air (2022)` and"
                    " `iPad Air 5th Gen`, one M1 twice. Apple's own names are the chip, and"
                    " which chip each generation and year carried is fixed history, so both"
                    " become the chip. `iPad mini (A17 Pro)` loses its brackets to match."
                ),
                body=_named_by_its_chip,
            ),
        ),
    ),
)
