"""Google, in phones. 445 offers across eight Latvian shops, measured 22.09.2026.

## The names Google gives a colour, and why they are read here rather than anywhere else

Google does not sell a black phone, it sells an `Obsidian` one. The category's rule reads a
colour out of a field and never out of a title, deliberately: cut from a title the word takes
358 forms across one shop's products, and canonicalising those by guessing splits one product
into several. This is not that. It is a closed list of one maker's own names, each one counted
across the shops that state a colour in a field beside it, and the layer exists for exactly
this — it is selected by `(category, brand)`, so nothing here can reach an Oppo.

That distinction is the whole reason this file can exist at all. `Canyon` is **pink on a
Google**, unanimously, and **orange on an Oppo**, unanimously. A row in
`attribute_value_aliases` is keyed on the word and a language, with no brand, so it would have
to make one of them wrong. Until that table grows a brand column, a maker's palette is code
and lives here.

## What was counted

Per shop, not per listing: five listings of one phone in one shop is one shop's opinion.

    canyon      pink    rdveikals 12, euronics 8                       2 shops, unanimous
    jade        green   bm 16, discover 2                              2 shops, unanimous
    indigo      blue    bm 6, bigbox 4, discover 4                     3 shops, unanimous
    porcelain   white   bm 28, discover 8, bigbox 6, euronics 4,       6 shops against 1,
                        onea 2, ksenukai 2; rdveikals says beige 9     and beige is close
    fog         green   bm 8, rdveikals 6, euronics 5, and rdveikals   3 shops against 1
                        light-green 12; dateks alone says grey 8

`frost` and `lemongrass` are here by a decision rather than by a count, and the difference is
written down because it matters. `frost` is contested — rdveikals says purple 12, euronics
says blue 6, and the judge asked as a straight choice between those two answered **neither**
at 0.89 and 0.91. `lemongrass` is not contested, it is thin: euronics says green on 6
listings and nobody says otherwise, which is one shop and the bar elsewhere here is two.
Both were settled by the person who owns this catalogue, and both can be argued with by
pointing at these numbers.

## Why the version moved to 2

The matching moved to `colours.from_title`, shared with Samsung's palette so that two
rulesets cannot disagree about what counts as a match, and it reads whole words rather than
spaces: `256GB Canyon,` was missed by the first version, which needed a space on both sides.

## Where this does not apply

Only when the reading has no colour yet. A shop that states the colour in a field has already
done this work for its own listings, and its answer is about the product it is selling; this
one is about a word. The field wins.
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
BRAND_KEY = "google"
VERSION = "google-phones-3"

# Google's own names for a colour, each one counted across the shops that state a colour in a
# field beside it. Deliberately a closed list: a name not here is not guessed at.
PALETTE = {
    "canyon": "pink",
    "jade": "green",
    "indigo": "blue",
    "porcelain": "white",
    "fog": "green",
    # Entered by a decision rather than by a count — see the rule's `why`.
    "lemongrass": "green",
    "frost": "purple",
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
                id="google-palette",
                layer=BRAND,
                why=(
                    "Google sells `Obsidian`, not black. Counted per shop rather than per"
                    " listing — five listings of one phone in one shop is one opinion —"
                    " five of its names are decided outright: `canyon` pink in 2 shops of 2,"
                    " `jade` green in 2 of 2, `indigo` blue in 3 of 3, `porcelain` white in 6"
                    " of 7, `fog` green in 3 of 4. This is the layer for it because the"
                    " answer belongs to the maker and not to the word: `Canyon` is pink here"
                    " and orange on an Oppo, both unanimous, so a row in"
                    " `attribute_value_aliases` — keyed on the word and a language, with no"
                    " brand — would have to make one of them wrong."
                    "\n\n"
                    "The judge was asked these first and got two of them backwards, at 0.93"
                    " and 0.92: `canyon` orange against 20 listings in 2 shops, `fog` grey"
                    " against 19 in 3. A bought opinion is worth having where the corpus is"
                    " silent, and worth less than counting where it is not."
                    "\n\n"
                    "Only when nothing else found a colour. A shop that states one in a field"
                    " has answered about the product it is selling; this rule answers about a"
                    " word, and the product wins."
                ),
                body=_palette,
            ),
            Rule(
                id="google-decided-by-hand",
                layer=BRAND,
                why=(
                    "`frost` and `lemongrass` are in the palette above by a decision, not by"
                    " a count, and this rule exists to say so where anybody changing the"
                    " palette will read it."
                    "\n\n"
                    "`lemongrass` is thin rather than contested: euronics says green on 6"
                    " listings and nothing says otherwise. One shop is one opinion and the"
                    " bar everywhere else here is two, so counting alone would leave it"
                    " undeclared and four listings unplaceable."
                    "\n\n"
                    "`frost` is genuinely contested and was settled anyway: rdveikals reads"
                    " it purple on 12, euronics blue on 6, and the judge — asked as a"
                    " straight choice between exactly those two — answered **neither** at"
                    " 0.89 and 0.91, the only confident answer in twelve such questions."
                    " Purple is the majority by listings and by nothing else. If a third"
                    " shop ever states it in a field, that is the number to look at."
                ),
            ),
        ),
    ),
)
