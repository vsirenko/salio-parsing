"""Samsung, in tablets.

Samsung's model code says which radio a tablet has: `SM-X930` is the Wi-Fi Galaxy Tab S11
Ultra and `SM-X936B` the 5G one, `SM-X130` the Wi-Fi Tab A11 and `SM-X135` the LTE. Discover
writes the code and no radio on 12 of its tablets — `Samsung X230 Galaxy Tab A11+ 11 128GB
Gray` — and every one of them waited in the queue for the axis the code already gave.
"""

import re
from typing import Any

from app.features.offers.normalization.rules import BRAND, Rule, Ruleset, Vocabulary, register

CATEGORY = "tablets"
BRAND_KEY = "samsung"
VERSION = "samsung-tablets-1"

CONNECTIVITY_KEY = "connectivity"
# `SM-X930NZAREUE`, `SM-X936B`, `SM-T505`, and discover's bare `X130` in front of `Galaxy`.
# The series letter, three digits, and at most the region and colour letters after them.
_CODE = re.compile(r"(?:\bSM-|\b)([TPX])(\d{3})(?:[A-Z]{0,4}[A-Z0-9]{0,6})?\b")
# The last digit: 0 is Wi-Fi, 5 is LTE, 6 is 5G.
_RADIO = {"0": "wifi", "5": "cellular", "6": "cellular"}


def _code_radio(fields: dict[str, Any]) -> str | None:
    """The radio the model codes on the listing name, if they all name the same one."""
    text = " ".join(str(fields.get(key) or "") for key in ("title", "mpn", "_line")).upper()
    said = {_RADIO.get(found.group(2)[-1]) for found in _CODE.finditer(text)}
    said.discard(None)
    return said.pop() if len(said) == 1 else None


def _connectivity_from_the_code(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The radio the code names; where the reading names the other one, neither."""
    radio = _code_radio(fields)
    if radio is None:
        return {}
    identity = dict(fields.get("identity") or {})
    read = identity.get(CONNECTIVITY_KEY)
    if read == radio:
        return {}
    if read is None:
        return {"identity": {**identity, CONNECTIVITY_KEY: radio}}
    identity.pop(CONNECTIVITY_KEY)
    return {"identity": identity}


RULESET = register(
    BRAND,
    (CATEGORY, BRAND_KEY),
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="samsung-tablets-connectivity-from-the-code",
                layer=BRAND,
                why=(
                    "Measured on 24.09.2026 over every shop's Samsung tablets that carry a"
                    " model code in the title, the part number or discover's bracket: a"
                    " code ending in 0 was read Wi-Fi on 133 and cellular on 3, one ending"
                    " in 5 or 6 cellular on 165 and Wi-Fi on none. The 3 are ksenukai's and"
                    " 1a's `Active5 Pro Wi-Fi SM-X350, …, 5G`, whose own name says Wi-Fi and"
                    " whose spec tail says 5G — the reading was the wrong one. So where the"
                    " reading has no radio the code gives it: 12 of discover's tablets"
                    " named the code and nothing else. Where the reading names the other"
                    " radio, neither is taken, as with any two sources that disagree."
                ),
                body=_connectivity_from_the_code,
            ),
        ),
    ),
)
