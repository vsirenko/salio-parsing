"""OnePlus, in phones. Measured across the eleven shops on 22.09.2026.

OnePlus names a colour the way Google and Samsung do — a word of its own — so the palette
is the same shape as theirs and counted the same way: per shop, because five listings of
one phone in one shop is one opinion.

    charcoal   black   3 shops of 3    rdveikals 6, discover 4, bigbox 3
    pitch      black   3 of 3
    phantom    grey    3 of 3
    eclipse    black   2 of 2
    mist       grey    5 of 6
    marble     grey    5 of 6
    dry ice    blue    1 of 1          rdveikals, 3 listings, nothing against it

`dry ice` is the one entered by a decision rather than by the bar: one shop is one opinion
and the bar here is two, but nothing contradicts it and three listings could not be placed
without it. The judge, asked, said grey at 0.54 and 0.76 — under the threshold and against
the only shop that states the colour in a field.
"""

from typing import Any

from app.features.offers.normalization import colours
from app.features.offers.normalization.rules import (
    BRAND,
    Rule,
    Ruleset,
    Vocabulary,
    register,
)

CATEGORY = "phones"
BRAND_KEY = "oneplus"
VERSION = "oneplus-phones-1"

# A phrase where the maker uses one — `Dry Ice` is two words and neither half is a colour.
PALETTE = {
    "charcoal": "black",
    "pitch": "black",
    "phantom": "grey",
    "eclipse": "black",
    "mist": "grey",
    "marble": "grey",
    "dry ice": "blue",
}


def _palette(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The maker's name for a colour, when nothing else found one."""
    identity = fields.get("identity", {})
    if identity.get("color"):
        return {}
    found = colours.from_title(fields.get("title") or "", PALETTE)
    return {"identity": {**identity, "color": found}} if found else {}


RULESET = register(
    BRAND,
    (CATEGORY, BRAND_KEY),
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="oneplus-palette",
                layer=BRAND,
                why=(
                    "Counted per shop rather than per listing, as the other palettes are:"
                    " `charcoal` black in 3 shops of 3, `pitch` black in 3 of 3, `phantom`"
                    " grey in 3 of 3, `eclipse` black in 2 of 2, `mist` grey in 5 of 6,"
                    " `marble` grey in 5 of 6. None of them is contested."
                    "\n\n"
                    "`dry ice` is the exception and is entered by a decision: rdveikals"
                    " states blue on 3 listings and no other shop states it at all, which is"
                    " one shop where the bar is two. Nothing contradicts it, and three"
                    " listings could not be placed without it. The judge said grey at 0.54"
                    " and 0.76 — under the threshold, and against the only shop that has"
                    " looked at the phone."
                    "\n\n"
                    "It is a phrase because neither half of it is a colour, which is why"
                    " `colours.from_title` takes multi-word keys."
                ),
                body=_palette,
            ),
        ),
    ),
)
