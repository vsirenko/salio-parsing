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

Nothing is written here yet, on purpose: telling colour from region needs the colour table
that does not exist, and this is the wrong place to guess one.
"""

from app.features.offers.normalization.rules import BRAND, Rule, Ruleset, register

CATEGORY = "phones"
BRAND_KEY = "samsung"
VERSION = "samsung-phones-0"

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
        ),
    ),
)
