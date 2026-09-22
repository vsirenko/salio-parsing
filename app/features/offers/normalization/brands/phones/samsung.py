"""Samsung, in phones. 332 offers across two Latvian shops, measured 22.09.2026.

## How Samsung numbers a phone

`SM-A176BZKAEUE`: `SM-` then the model, then letters that carry the colour, then a region.
The shape looks like Apple's and behaves nothing like it. Measured here, `SM-A176BZ` is the
start of six distinct part numbers:

    SM-A176BZAAEUE  SM-A176BZADEUE  SM-A176BZBAEUE
    SM-A176BZKAEEE  SM-A176BZKAEUE  SM-A176BZKDEUE

Apple's trailing pair is noise. Samsung's trailing letters are **half the product**: the
colour is a real variant axis, and two of the six above differ only in their last three
characters, which is a region and is noise. Truncating the way Apple's rule could would
merge phones that are genuinely different.

One shop also publishes `2BN-SM-S918B/DS/256/WT` — its own prefix wrapped around Samsung's
code, with the capacity and colour spelled out after it. That is a shop's habit rather than
Samsung's and belongs in the shop's rules if it is worth having at all.

Nothing is written about the part number here, on purpose: telling colour from region needs
the colour table that does not exist, and this is the wrong place to guess one.

## The names Samsung gives a colour

What *is* written is the palette. Samsung sells `Cobalt Violet`, not purple, and the shops
that state a colour in a field of their own are the evidence for what each name means. Counted
per shop rather than per listing — five listings of one phone in one shop is one opinion:

    cobalt       purple   9 shops, none against, 217 listings   `Cobalt Violet`
    silverblue   silver   6 against 1, 40                       `Titanium Silverblue`
    jadegreen    green    5 against 0, 19                       `Titanium Jadegreen`
    techno       purple   4 against 0, 27                       `Techno Violet`
    whitesilver  white    4 against 1, 20                       `Titanium Whitesilver`
    blueberry    purple   3 against 1, 18                       rdveikals alone says blue
    graygreen    green    2 against 1, 14                       tet alone says grey
    amber        yellow   2 against 0, 8                        `Amber Yellow`

Three are left undeclared below, which is the point of declaring them: `charcoal`,
`coralred` and `pinkgold`. A rule that guessed them would file a phone under the wrong
colour, and a wrong colour cannot be told from a right one afterwards.
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
BRAND_KEY = "samsung"
VERSION = "samsung-phones-2"

# Samsung's own names for a colour, each counted across the shops that state one in a field
# beside it. A closed list on purpose: a name not here is not guessed at.
PALETTE = {
    "cobalt": "purple",
    "techno": "purple",
    "jadegreen": "green",
    "silverblue": "silver",
    "whitesilver": "white",
    "blueberry": "purple",
    "graygreen": "green",
    "amber": "yellow",
    # Settled by a decision, with the counts in the rule below.
    "charcoal": "black",
    "coralred": "red",
}


def _palette(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The maker's name for a colour, read off the title, when nothing else found one."""
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
                id="samsung-model-from-part-number",
                layer=BRAND,
                why=(
                    "`SM-A176BZ` begins six different part numbers in this corpus, and the"
                    " letters that follow are not one thing: some of them are the colour,"
                    " which tells two phones apart, and some are a region, which does not."
                    " Cutting at a fixed length the way Apple's part numbers allow would"
                    " merge phones that really are different. Separating the two needs the"
                    " colour table that does not exist yet — `phones-color` is declared and"
                    " unwritten for the same reason — and guessing here would produce"
                    " confident merges rather than visible gaps."
                ),
            ),
            Rule(
                id="samsung-palette",
                layer=BRAND,
                why=(
                    "Samsung sells `Cobalt Violet`, not purple. Eight of its names are"
                    " decided outright by the shops that state a colour in a field —"
                    " counted per shop, because five listings of one phone in one shop is"
                    " one opinion: `cobalt` purple in 9 shops of 9 and 217 listings,"
                    " `silverblue` silver in 6 of 7, `jadegreen` green in 5 of 5, `techno`"
                    " purple in 4 of 4, `whitesilver` white in 4 of 5, `blueberry` purple in"
                    " 3 of 4, `graygreen` green in 2 of 3, `amber` yellow in 2 of 2."
                    "\n\n"
                    "This layer rather than the registry, because the answer belongs to the"
                    " maker and not to the word. `Canyon` is pink on a Google and orange on"
                    " an Oppo, both unanimous, and `attribute_value_aliases` is keyed on the"
                    " word and a language with no brand — so a row there would have to make"
                    " one of them wrong."
                    "\n\n"
                    "It fires only where nothing else found a colour. A shop that states one"
                    " in a field has answered about the product it is selling; this answers"
                    " about a word, and the product wins."
                ),
                body=_palette,
            ),
            Rule(
                id="samsung-pinkgold",
                layer=BRAND,
                why=(
                    "`Titanium Pinkgold` is declared and left unwritten: one shop,"
                    " rdveikals on 3 listings, and the bar the others cleared is two."
                    "\n\n"
                    "`charcoal` and `coralred` were here beside it and are now in the"
                    " palette, both by a decision, and the reasoning belongs where somebody"
                    " changing them will read it."
                    "\n\n"
                    "`charcoal` looked like 3 shops for black against 2 for grey, which is"
                    " not a majority worth acting on — until the votes were read. **dateks"
                    " says both**: black on the Enterprise Edition of the A37 and grey on"
                    " the plain one, the same phrase on the same phone. A shop contradicting"
                    " itself is not one vote on each side, it is no vote at all, and without"
                    " it the count is black at tet and bm against grey at rdveikals: two"
                    " shops to one, which is the ordinary bar. The judge answered black at"
                    " 0.66 and 0.73 — under the threshold, but pointing the same way."
                    "\n\n"
                    "`coralred` is red at bm on 4 and coral at rdveikals on 3, one shop"
                    " each, and it was never a disagreement about the colour — only about"
                    " how finely to name it. It is settled by removing `coral` from the"
                    " registry rather than by choosing here: 2 catalogue entries and 2"
                    " listings sat under it against 73 and 169 under `red`, so it divided"
                    " the red phones and distinguished nothing."
                ),
            ),
        ),
    ),
)
