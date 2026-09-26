"""Apple, in phones. 165 offers across two Latvian shops, measured 22.09.2026.

## How Apple numbers a phone

The part number is five characters of configuration, two of market, then `/A`:
`MG014` + `HX` + `/A`. Apple publishes its own lists in that form and says the last pair
varies by country or region, which is the same as saying **the market code does not change
the machine** — `MG014HX/A` and `MG014QN/A` are one phone sold in two places.

Measured here: 96 configurations carry this form, and 9 of them are split across more than
one market code. Every one of those 9 agrees on capacity, so in this corpus collapsing them
would be safe.

## Why it is not collapsed anyway

The older corpus, on laptops rather than phones, found three configuration prefixes out of
sixty-six where the storage or the memory genuinely differed between market codes. Three in
sixty-six is small and it is not zero, and the failure is the bad kind: two different
machines filed as one, confidently, with no queue entry to say it happened.

So the configuration is recorded as an axis beside the others rather than written over the
part number. An identity key built from brand, category and the identity-bearing axes then
separates the disputed cases by capacity, which is the check the older corpus said was
needed — and does it by construction instead of by a rule remembering to.
"""

import re
from typing import Any

from app.features.offers.normalization import colours
from app.features.offers.normalization.rules import BRAND, Rule, Ruleset, Vocabulary, register

CATEGORY = "phones"
BRAND_KEY = "apple"
VERSION = "apple-phones-3"

# `MG014HX/A`: five of configuration, two of market, then the suffix Apple puts on
# everything it sells at retail.
PART_NUMBER = re.compile(r"^([A-Z0-9]{5})([A-Z]{2})/A$")

# Apple's own names for a colour, as phrases: the word alone is not the unit, because
# `Cosmic Orange` and `Cosmic Black` share one. Only the two the shops agree about — the
# rest are declared and unwritten below.
PALETTE = {
    "desert titanium": "gold",
    "natural titanium": "grey",
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


def _configuration(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    found = PART_NUMBER.match(str(fields.get("mpn") or "").strip().upper())
    if not found:
        return {}
    return {
        "identity": {
            **fields.get("identity", {}),
            "apple_config": found.group(1),
            # Kept rather than discarded: which market a listing was numbered for is a fact
            # about the listing, and the day two of them disagree it is the first thing
            # anybody will want to see.
            "apple_market": found.group(2),
        }
    }


# Apple numbers the iPhone SE by generation and the shops by year: 2016 is the first, 2020
# the second, 2022 the third — Apple's own model list.
SE_GENERATIONS = {"2016": "1st", "2020": "2nd", "2022": "3rd"}
_SE = re.compile(r"^iphone se$", re.IGNORECASE)
_YEAR = re.compile(r"(?<!\d)(2016|2020|2022)(?!\d)")


def _se_generation(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """`iPhone SE` with the generation its year names, where the title names exactly one."""
    model = str(fields.get("model") or "").strip()
    if not _SE.match(model):
        return {}
    years = set(_YEAR.findall(str(fields.get("title") or "")))
    if len(years) != 1:
        return {}
    return {"model": f"iPhone SE ({SE_GENERATIONS[years.pop()]} generation)"}


RULESET = register(
    BRAND,
    (CATEGORY, BRAND_KEY),
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="apple-configuration-from-part-number",
                layer=BRAND,
                why=(
                    "Apple's part number is five characters of configuration, two of market"
                    " and `/A`, and the market pair does not change the machine — Apple says"
                    " so in its own model lists. 96 configurations in this corpus carry the"
                    " form and 9 are split across market codes, which is 9 products that"
                    " look like 18. Recording the configuration makes the split visible to"
                    " an identity key without overwriting what the shop actually published."
                ),
                body=_configuration,
            ),
            Rule(
                id="apple-collapse-market-code",
                layer=BRAND,
                why=(
                    "Writing the configuration over `mpn` would merge those 9 outright, and"
                    " every one of them agrees on capacity here, so it would be correct on"
                    " this data. It is declared and not written because a larger corpus"
                    " disagrees: on laptops, three configuration prefixes out of sixty-six"
                    " had storage or memory differing between market codes. Three in"
                    " sixty-six is small and not zero, and the failure mode is the bad one —"
                    " two machines filed as one, confidently, with nothing queued to say it"
                    " happened. The identity key is where this belongs, because it compares"
                    " capacity at the same time instead of trusting a rule to remember."
                ),
            ),
            Rule(
                id="apple-palette",
                layer=BRAND,
                why=(
                    "`titanium` was a value in the colour registry and had to go: it is a"
                    " material, not a colour, and it was winning. `Blue Titanium` read as"
                    " titanium, `Desert Titanium` read as titanium, and two catalogue"
                    " entries held the desert, the natural and the white iPhone 16 Pro Max"
                    " as one product with their prices compared as one. Removing it let 205"
                    " of the 248 titanium-titled listings read a real colour — black 73,"
                    " silver 44, grey 30, blue 23, white 19 — because the other word in the"
                    " phrase was the colour all along."
                    "\n\n"
                    "What it did not settle is the two phrases where the other word is"
                    " Apple's own. `Desert Titanium` is gold: one Apple shop states it in a"
                    " field, and `desert` reads gold in 4 shops of 4 across every maker that"
                    " uses it, which is the case where a word is not a maker's invention but"
                    " a plain description. `Natural Titanium` is grey on one shop's 5"
                    " listings and nobody contradicts it — the phrase names unpainted metal."
                    "\n\n"
                    "Phrases rather than words, because `Cosmic Orange` and `Cosmic Black`"
                    " share a word and are two colours. That is also why the palette holds"
                    " no single word that appears inside one of its phrases."
                ),
                body=_palette,
            ),
            Rule(
                id="apple-contested-titanium",
                layer=BRAND,
                why=(
                    "`Lunar Titanium` and `Stellar Titanium` are declared and unwritten."
                    " `Lunar` gets four different answers from four shops — grey, white,"
                    " blue and a two-tone — which is not a disagreement to resolve but an"
                    " absence of evidence. `Stellar` is blue in 3 shops, silver in 2 and"
                    " black in 1, which is a real split. Half a canonicalisation is worse"
                    " than none: a colour mapped wrongly splits one product into several,"
                    " confidently."
                ),
            ),
            Rule(
                id="apple-se-generation-from-the-year",
                layer=BRAND,
                why=(
                    "Apple has sold three iPhone SEs and names them by generation; the shops"
                    " name them by year, and bm writes it after the capacity — `Apple iPhone"
                    " SE 256GB (2022) Starlight MMXN3` — where no registry name can reach it."
                    " On 26.09.2026 three such entries sat under a bare `iPhone SE` beside"
                    " `iPhone SE 3` and `iPhone SE (2022) 5G`, one phone in three families."
                    " The year is Apple's: 2016 the first, 2020 the second, 2022 the third."
                    " Only where the title names exactly one of them."
                ),
                body=_se_generation,
            ),
        ),
    ),
)
