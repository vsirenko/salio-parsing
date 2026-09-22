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

from app.features.offers.normalization.rules import BRAND, Rule, Ruleset, Vocabulary, register

CATEGORY = "phones"
BRAND_KEY = "apple"
VERSION = "apple-phones-1"

# `MG014HX/A`: five of configuration, two of market, then the suffix Apple puts on
# everything it sells at retail.
PART_NUMBER = re.compile(r"^([A-Z0-9]{5})([A-Z]{2})/A$")


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
        ),
    ),
)
