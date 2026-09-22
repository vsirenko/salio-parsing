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

`frost` is the one that is genuinely contested and it is left undeclared below rather than
guessed: rdveikals says purple 9, euronics says blue 3, and two shops disagreeing is not a
majority of one. The judge was asked and answered `white` at 0.46, under the threshold — three
opinions, no two alike, which is what an unanswerable question looks like.

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
VERSION = "google-phones-2"

# Google's own names for a colour, each one counted across the shops that state a colour in a
# field beside it. Deliberately a closed list: a name not here is not guessed at.
PALETTE = {
    "canyon": "pink",
    "jade": "green",
    "indigo": "blue",
    "porcelain": "white",
    "fog": "green",
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
                id="google-frost",
                layer=BRAND,
                why=(
                    "`Frost` is left undeclared on purpose. rdveikals reads it purple on 9"
                    " and euronics blue on 3 — two shops disagreeing is not a majority of"
                    " one — and the judge answered `white` at 0.46, which is a third opinion"
                    " and under the threshold. Three answers and no two alike is what an"
                    " unanswerable question looks like, and half a canonicalisation is worse"
                    " than none: a colour mapped wrongly splits one product into several,"
                    " confidently. It needs a photograph, like `Night Sky` does."
                ),
            ),
        ),
    ),
)
