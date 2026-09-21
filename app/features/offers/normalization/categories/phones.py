"""What a phone listing means, whichever shop it came from.

Written against 520 real phones collected on 21.09.2026. Everything here is about the kind
of product rather than about a shop: where a shop hides its storage figure is a source
rule, but that storage is what tells two otherwise identical phones apart is true of every
shop that sells them.
"""

import re
from typing import Any

from app.features.offers.normalization.rules import CATEGORY, Rule, Ruleset, register

SLUG = "phones"
VERSION = "phones-1"

# Attribute names, in the languages the Baltic shops write them, that hold the capacity.
STORAGE_KEYS = ("atmiņas ietilpība", "storage", "memory", "capacity", "iekšējā atmiņa")
# Everything converts to megabytes exactly, and nothing has to be a fraction.
SCALE = {"MB": 1, "GB": 1024, "TB": 1024 * 1024}
_SIZE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s?(TB|GB|MB)\b", re.IGNORECASE)


def _storage(payload: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
    """Capacity as an exact number of megabytes, from the attributes or from the title."""
    attributes = fields.get("attributes") or {}
    for name, value in attributes.items():
        if str(name).strip().lower() in STORAGE_KEYS:
            megabytes = _megabytes(str(value))
            if megabytes is not None:
                return {"identity": {**fields.get("identity", {}), "storage_mb": megabytes}}

    megabytes = _megabytes(fields.get("title") or "")
    if megabytes is None:
        return {}
    return {"identity": {**fields.get("identity", {}), "storage_mb": megabytes}}


def _megabytes(text: str) -> int | None:
    found = _SIZE.search(text)
    if not found:
        return None
    amount = float(found.group(1).replace(",", "."))
    return int(amount * SCALE[found.group(2).upper()])


RULESET = register(
    CATEGORY,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="phones-storage",
                layer=CATEGORY,
                why=(
                    "Capacity is what tells two otherwise identical phones apart, and it is"
                    " written in two places and three units: an attribute on 98.5% of these"
                    " products and the title on 96.9%, as GB on 429, TB on 26 and MB on 49."
                    " Megabytes rather than gigabytes because everything converts to them"
                    " exactly: a feature phone with 32 MB would otherwise be 0.03125 GB, and"
                    " an identity axis that is a fraction is an identity axis that will"
                    " eventually be compared wrongly."
                ),
                body=_storage,
            ),
            Rule(
                id="phones-color",
                layer=CATEGORY,
                why=(
                    "Colour is the other axis that splits a phone into variants, and it"
                    " cannot be read here yet. Across 520 products the word before `krās`"
                    " takes 61 distinct forms, and they are three different problems wearing"
                    " one shape: Latvian declension (`melns` and `melna` are one colour),"
                    " plain language (`black` is the same colour again), and the maker's own"
                    " marketing (`obsidian`, `glacier`, `shadow`). Only the first is a"
                    " category's business. The second needs a language table, and the third"
                    " is brand knowledge — Google is the one who decided obsidian means"
                    " black. Declared unwritten rather than half-written: a colour that is"
                    " canonicalised wrongly splits one product into several with confidence."
                ),
            ),
        ),
    ),
)
