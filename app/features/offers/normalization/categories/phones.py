"""What a phone listing means, whichever shop it came from.

Written against 520 real phones collected on 21.09.2026. Everything here is about the kind
of product rather than about a shop: where a shop hides its storage figure is a source
rule, but that storage is what tells two otherwise identical phones apart is true of every
shop that sells them.
"""

import re
from typing import Any

from app.features.offers.normalization import colours
from app.features.offers.normalization.rules import CATEGORY, Rule, Ruleset, Vocabulary, register

SLUG = "phones"
# Bumped when a rule body changes, not only when a rule is added: the version is
# what a reparse compares to decide whether a stored reading is stale, so a fix
# that leaves it alone is a fix that never reaches the rows it was written for.
VERSION = "phones-5"

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
# Same stopgap, same reason: nothing resolves an attribute *name* through the registry
# yet. The values behind it do resolve now, which is the half that mattered.
COLOR_NAMES = ("krāsa", "color", "colour")
# Everything converts to megabytes exactly, and nothing has to be a fraction.
SCALE = {"MB": 1, "GB": 1024, "TB": 1024 * 1024}
# The largest capacity a phone has ever shipped with. Not a limit on what may be
# stored — a bound on what a reading may claim, which is what tells a unit that was
# borrowed from the other half of a pair from one that was really written.
LARGEST_PHONE_MB = 2 * 1024 * 1024
_SIZE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s?(TB|GB|MB)\b", re.IGNORECASE)
# `128/4 GB`, `512/12 GB` — a pair sharing one unit at the end. Both halves are sizes and
# only the second is spelled as one, so a search for units alone finds the wrong half.
_SHARED_UNIT = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s*/\s*(\d+(?:[.,]\d+)?)\s?(TB|GB|MB)\b", re.IGNORECASE
)


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


def _color(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """Colour as the canonical value, from whatever the shop called the field.

    Only from a field. Cutting a colour out of a title is what kept this rule unwritten for
    as long as it was: across one shop's 1153 titled products the word takes 358 forms, most
    of them a maker's invention — `Obsidian`, `Glacier`, `Cosmic Orange` — and canonicalising
    those by guessing splits one product into several, confidently. A shop that states the
    colour in a field has already done that work, in 37 forms rather than 358.

    Resolved through the vocabulary the caller handed in, never a table this module carries:
    the spellings are Latvian today and Lithuanian at the next shop, and both belong in
    `attribute_value_aliases` with their language.
    """
    if not vocabulary.colours:
        return {}
    for name, value in (fields.get("attributes") or {}).items():
        if not any(word in name.lower() for word in COLOR_NAMES):
            continue
        canonical = _canonical(str(value).strip(), vocabulary)
        if canonical:
            return {"identity": {**fields.get("identity", {}), "color": canonical}}
    return {}


def _canonical(value: str, vocabulary: Vocabulary) -> str | None:
    """The registry's value for what a shop wrote in its colour field.

    Through `colours`, not a dictionary lookup. An exact lookup is what this was for as long
    as the only shops here stated one word; the two that state a phrase — `light blue`,
    `tumši zils` — got nothing from it, 104 products between them.

    A field naming more than one colour is a two-tone case and is resolved as a pair, never
    by taking one of them. Dropping words off the front, which is what resolves `light blue`,
    reads `black, orange` as `orange`: not a partial answer but a wrong one, and a product
    filed under the wrong colour cannot be told from one filed under the right one.
    """
    # The registry first, on the phrase exactly as the shop wrote it. It knows some whole
    # phrases — `Melna / Oranža` is one alias, not two — and taking those apart to put them
    # back together again is how a known answer turns into a guess.
    known = vocabulary.colours.get(value.casefold())
    if known:
        return known

    parts = [part.strip() for part in re.split(r"[,/]", value) if part.strip()]
    if len(parts) > 1:
        return colours.pair(parts, vocabulary)
    return colours.resolve(value, vocabulary)


def _megabytes(text: str) -> int | None:
    """The largest size in the text, because a title that carries two carries both kinds.

    On a phone the built-in capacity is always the larger of the two, and that is the whole
    rule — it holds whichever order a shop writes them in, which matters because they do not
    agree. One writes `12GB/512GB`, working memory first; another writes `128/4 GB`, capacity
    first and with a single unit at the end. Taking the first number read the second shop's
    phones as having four gigabytes of space; searching only for numbers that carry a unit
    read them the same way, because in `128/4 GB` only the `4` has one.

    Lending the unit to the unspelled half is right far more often than not, and absurd the
    rest of the time: `12/1 TB` is twelve *gigabytes* of memory beside a terabyte of storage,
    and read as written it claims twelve terabytes. So a reading larger than any phone has
    ever shipped with is discarded — which settles it without this rule having to know which
    half of a pair is which.

    Found by disagreement rather than by inspection, twice over: two shops selling the same
    barcode reported 128 GB and 4 GB, and a barcode is proof that it is one phone. Fixing
    that produced the second kind, and the same comparison caught it.
    """
    sizes = [_size(amount, unit) for amount, unit in _SIZE.findall(text)]
    # A pair sharing one unit contributes both of its halves, not just the spelled one.
    for first, second, unit in _SHARED_UNIT.findall(text):
        sizes += [_size(first, unit), _size(second, unit)]

    believable = [size for size in sizes if size <= LARGEST_PHONE_MB]
    return max(believable) if believable else None


def _size(amount: str, unit: str) -> int:
    return int(float(amount.replace(",", ".")) * SCALE[unit.upper()])


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
                    " title the largest size wins, whichever order a shop writes the pair"
                    " in: one writes `12GB/512GB`, RAM first, and another `128/4 GB`,"
                    " capacity first with a single unit at the end. Taking the first read"
                    " a phone as having half a gigabyte; reading only the half that"
                    " carries a unit read another as having four."
                ),
                body=_storage,
            ),
            Rule(
                id="phones-color",
                layer=CATEGORY,
                why=(
                    "The other axis that splits a phone into variants, and the one that"
                    " stayed unwritten longest. Cut out of a title the word takes 358 forms"
                    " across one shop's 1153 titled products, and they are three problems"
                    " wearing one shape: Latvian declension, plain language, and the maker's"
                    " own marketing — `Obsidian`, `Glacier`, `Cosmic Orange`. Only the first"
                    " is a category's business, and canonicalising the third by guessing"
                    " splits one product into several with confidence."
                    "\n\n"
                    "What unblocked it was a shop that states colour in a field rather than"
                    " leaving it in a title: 99.9% of its 1396 phones, in 37 forms rather"
                    " than 358, already reduced to real colours by whoever runs the shop."
                    " So this reads a field and never a title, and resolves it through the"
                    " registry the caller loaded — 37 canonical values with their Latvian"
                    " and plain-English spellings. The marketing names are deliberately not"
                    " in it: the pairs that could be learned from that one shop include"
                    " `evening blue` meaning grey and `desert titanium` meaning gold, which"
                    " is the confident wrong answer this rule existed to avoid."
                    "\n\n"
                    "The lookup was exact for as long as every shop that stated a colour"
                    " stated one word. Two of them state a phrase — `light blue`,"
                    " `tumši zils` — and got nothing at all: 104 products between dateks and"
                    " euronics. It resolves through `colours` now, which reads a phrase by"
                    " dropping words off the front, and that brings 93 of them in. The other"
                    " 11 are a field naming two or three colours at once, and they are"
                    " refused rather than reduced: dropping words off the front reads"
                    " `black, orange` as `orange`, which is not a partial answer but a wrong"
                    " one. A separated field is resolved as a pair or not at all."
                ),
                body=_color,
            ),
        ),
    ),
)
