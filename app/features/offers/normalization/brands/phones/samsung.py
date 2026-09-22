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
VERSION = "samsung-phones-1"

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
                id="samsung-contested-names",
                layer=BRAND,
                why=(
                    "`Awesome Charcoal`, `Coralred` and `Titanium Pinkgold` are declared and"
                    " left unwritten, which is the whole point of declaring them."
                    "\n\n"
                    "`charcoal` is black in 3 shops and grey in 2, and **dateks says both**"
                    " — black on the Enterprise Edition of the A37 and grey on the plain"
                    " one, which is the same phrase and the same phone. A shop contradicting"
                    " itself is not evidence, and 3 against 2 is not a majority worth acting"
                    " on. The judge was asked and answered black at 0.66 and 0.73, under the"
                    " threshold: a fourth opinion, no more decisive than the other three."
                    "\n\n"
                    "`coralred` is red at bm and coral at rdveikals, one shop each. The"
                    " registry holds both values, so this is not two shops disagreeing about"
                    " a colour so much as about how fine a colour is — which is a question"
                    " about the registry and is answered there, not here."
                    "\n\n"
                    "`pinkgold` has one shop behind it, rdveikals on 3 listings. One shop is"
                    " one opinion, and the bar the other eight names cleared is two."
                ),
            ),
        ),
    ),
)
