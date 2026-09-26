"""Reading shop.cec.lv's MacBooks.

Apart from `cec.py` because a rule here imports the laptop category, and a ruleset's
fingerprint covers what its module imports. Written against the 87 MacBooks collected on
25.09.2026: 82 variants of configurable families, whose options carry the keyboard as
`erply_language` — a registry row, not a rule — and five simple products, whose options are
empty and whose name ends in it instead.
"""

from typing import Any

from app.features.offers.normalization.categories import laptops
from app.features.offers.normalization.rules import SOURCE, Rule, Ruleset, Vocabulary, register

LAPTOPS_SLUG = "cec-laptops"
LAPTOPS_VERSION = "cec-laptops-7"
BRAND = "Apple"


def _brand(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    if fields.get("brand_raw"):
        return {}
    category = str(payload.get("category") or "").strip()
    return {"brand_raw": BRAND} if category.startswith("MacBook") else {}


def _keyboard_at_the_end_of_the_name(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """`MacBook Air 13” Apple M5 …/512GB SSD/Midnight/INT`: the last segment, when the
    registry knows it for a layout."""
    if (fields.get("identity") or {}).get(laptops.KEYBOARD_KEY):
        return {}
    name = str(payload.get("name") or "")
    if "/" not in name:
        return {}
    layout = laptops.keyboard_word(vocabulary, name.rsplit("/", 1)[1].strip())
    if layout is None:
        return {}
    return {"identity": {**(fields.get("identity") or {}), laptops.KEYBOARD_KEY: layout}}


LAPTOPS_RULESET = register(
    SOURCE,
    LAPTOPS_SLUG,
    Ruleset(
        version=LAPTOPS_VERSION,
        rules=(
            Rule(
                id="cec-laptops-brand",
                layer=SOURCE,
                why=(
                    "An Apple reseller that states no brand on its MacBooks either: none of the"
                    " 87 of 25.09.2026 resolved a maker, so Apple's own laptop rules never ran"
                    ' and `MacBook Pro 14" Apple M5 Pro` was read as a model `Pro 14`.'
                ),
                body=_brand,
            ),
            Rule(
                id="cec-laptops-keyboard-at-the-end-of-the-name",
                layer=SOURCE,
                why=(
                    "Five of the 87 are simple products with no options, and their name ends"
                    " in the keyboard — `…/Midnight/INT`, `…/Silver/USA` — where the other 82"
                    " state it as `erply_language`. Only a word the registry knows."
                ),
                body=_keyboard_at_the_end_of_the_name,
            ),
        ),
    ),
)
