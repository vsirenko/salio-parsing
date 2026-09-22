"""What a phone listing means, whichever shop it came from.

Written against 520 real phones collected on 21.09.2026. Everything here is about the kind
of product rather than about a shop: where a shop hides its storage figure is a source
rule, but that storage is what tells two otherwise identical phones apart is true of every
shop that sells them.
"""

import re
from typing import Any

from app.features.offers.normalization.rules import CATEGORY, Rule, Ruleset, Vocabulary, register

SLUG = "phones"
VERSION = "phones-1"

# ---------------------------------------------------------------------------------------
# STOPGAP. These two tuples are vocabulary, and vocabulary does not belong in code.
#
# That `Iekšējā atmiņa` means built-in storage is a Latvian fact about a word. It belongs in
# `attribute_aliases`, which has a `language` column for exactly this, and which nothing
# resolves through yet. What belongs here is the structure: that built-in storage tells two
# phones apart and working memory does not, which is true in every language.
#
# **Do not add a second language beside these.** A Lithuanian `talpa` and an Estonian `mälu`
# written here turn a category into a dictionary, and the dictionary we already built stays
# empty. Add the resolution step instead — see TODO.md.
# ---------------------------------------------------------------------------------------

# Fragments of the names the Baltic shops give the built-in capacity. Matched as a
# substring rather than whole, because a shop writes the unit into the name itself:
# ksenukai says `Atmiņas ietilpība` and bigbox says `Iekšējā atmiņa, GB`.
STORAGE_NAMES = ("atmiņas ietilpība", "iekšējā atmiņa", "storage", "internal memory", "capacity")
# And the one thing that reliably tells the other kind of memory apart. Both shops name it
# the same way, and reading it as capacity is the mistake this guards against: a phone
# listed `12GB/512GB` is twelve of working memory and five hundred and twelve of storage.
RAM_NAMES = ("ram", "operatīvā")
# Everything converts to megabytes exactly, and nothing has to be a fraction.
SCALE = {"MB": 1, "GB": 1024, "TB": 1024 * 1024}
_SIZE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s?(TB|GB|MB)\b", re.IGNORECASE)


def _storage(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """Capacity as an exact number of megabytes, from the attributes or from the title."""
    for name, value in (fields.get("attributes") or {}).items():
        lowered = str(name).strip().lower()
        if any(ram in lowered for ram in RAM_NAMES):
            continue
        if any(storage in lowered for storage in STORAGE_NAMES):
            megabytes = _megabytes(str(value))
            if megabytes is not None:
                return {"identity": {**fields.get("identity", {}), "storage_mb": megabytes}}

    megabytes = _megabytes(fields.get("title") or "")
    if megabytes is None:
        return {}
    return {"identity": {**fields.get("identity", {}), "storage_mb": megabytes}}


def _megabytes(text: str) -> int | None:
    """The largest size in the text, because a title that carries two carries both kinds.

    `Tālrunis Oukitel WP56 5G 12GB/512GB Black` is working memory and then storage, in that
    order, and taking the first one reads a phone as having half a gigabyte of space. On a
    phone the built-in capacity is always the larger of the two.
    """
    found = _SIZE.findall(text)
    if not found:
        return None
    return max(int(float(amount.replace(",", ".")) * SCALE[unit.upper()]) for amount, unit in found)


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
                    " eventually be compared wrongly. Two traps, both met on real data:"
                    " a shop writes the unit into the attribute name (`Iekšējā atmiņa, GB`)"
                    " so names match as fragments, and working memory is named the same way"
                    " by both shops, so anything mentioning RAM is refused outright. In a"
                    " title the largest size wins — `12GB/512GB` is RAM and then storage,"
                    " and taking the first read a phone as having half a gigabyte."
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
