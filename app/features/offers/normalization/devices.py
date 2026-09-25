"""What a handheld device listing means — a phone, a tablet — whichever shop it came from.

Moved out of `categories/phones.py` on 23.09.2026, when tablets arrived and were measured
against these rules: over 1089 of m79's, the storage rule read 88% and the colour rules 68%
without a line changed. So the bodies live here and each category declares its own rules
around them, with its own reasons — what a rule *does* is shared, why a category has it is
not.
"""

import re
from typing import Any

from app.features.brands.normalization import normalize_brand
from app.features.offers.normalization import colours, models, naming
from app.features.offers.normalization.rules import Vocabulary

# The two identity axes, by the keys the registry files them under. Which of a shop's field
# names mean them is vocabulary and lives in `attribute_aliases`; that these two tell phones
# apart is structure and lives here.
STORAGE_KEY = "storage_mb"
COLOR_KEY = "color"
# Everything converts to megabytes exactly, and nothing has to be a fraction.
SCALE = {"MB": 1, "GB": 1024, "TB": 1024 * 1024}
# The largest capacity a phone or a tablet has ever shipped with. Not a limit on what may be
# stored — a bound on what a reading may claim, which is what tells a unit that was
# borrowed from the other half of a pair from one that was really written.
LARGEST_DEVICE_MB = 2 * 1024 * 1024
_SIZE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s?(TB|GB|MB)\b", re.IGNORECASE)
# `128/4 GB`, `512/12 GB` — a pair sharing one unit at the end. Both halves are sizes and
# only the second is spelled as one, so a search for units alone finds the wrong half.
_SHARED_UNIT = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s*/\s*(\d+(?:[.,]\d+)?)\s?(TB|GB|MB)\b", re.IGNORECASE
)


def storage(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """Capacity as an exact number of megabytes, from the attributes or from the title.

    Which of a shop's fields is the built-in storage is looked up, not guessed: the name is
    resolved through the registry the caller handed in, exactly, so working memory — a name
    that resolves to `ram_mb` — can never be read as storage however its words overlap.
    """
    stated = {
        size
        for name, value in (fields.get("attributes") or {}).items()
        if vocabulary.attribute_key(str(name)) == STORAGE_KEY
        and (size := megabytes(str(value))) is not None
    }
    titled = megabytes(fields.get("title") or "")
    agreed = _agreed(stated, titled)
    if agreed is None:
        return {}
    return {"identity": {**fields.get("identity", {}), "storage_mb": agreed}}


def _agreed(stated: set[int], titled: int | None) -> int | None:
    """The one capacity every source agrees on, or nothing.

    Measured over every shop on 23.09.2026: title and field named the same capacity 5150
    times and different ones 38, and neither was the one to trust — the rest of the market
    sided with the title 23 times (rdveikals writes `1 GB` for a 1 TB iPhone Air) and with
    the field 15 (bm's titles carry a size that is not the phone's). Any rule that ranked one
    over the other was wrong fifteen times or more, so a disagreement reads as nothing: an
    empty axis sends the listing the slow way round, a wrong one files it under another
    phone at confidence.

    One exception, because dateks lists the same capacity under several names from several
    datasheets and they disagree among themselves: where the title settles which of them is
    right, it is taken.
    """
    if titled is None:
        return next(iter(stated)) if len(stated) == 1 else None
    if not stated or stated == {titled} or titled in stated and len(stated) > 1:
        return titled
    return None


def color(
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
    stated = {
        canonical
        for name, value in (fields.get("attributes") or {}).items()
        if vocabulary.attribute_key(str(name)) == COLOR_KEY
        and (canonical := _canonical(str(value).strip(), vocabulary))
    }
    # A shop that states two colours for one product has not stated one. dateks carries
    # `melns`, `zils` and `Tumši zils` on a single black phone, from three datasheets; the
    # title rule below reads what the shop put in the name instead.
    if len(stated) != 1:
        return {}
    return {"identity": {**fields.get("identity", {}), "color": stated.pop()}}


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


# Words separated by spaces alone. Anything else between them — a slash, a comma, a bar —
# is the shop separating two colours, and joining those is how `black/orange` becomes
# `orange`: not a partial answer but a wrong one.
_RUN = re.compile(r"[^\W\d_]+(?:[ \t]+[^\W\d_]+)*", re.UNICODE)


def color_from_title(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """A colour the registry already knows, found as a whole word in the title.

    Not the thing the rule above refuses. That one refuses to *canonicalise* a word nobody
    entered — `Obsidian`, `Glacier`, `Cosmic Orange` — because guessing at one splits a
    product into several. This asks a different question: does the title contain a word the
    registry has already been given an answer for? That is a lookup, and a word nobody
    entered produces nothing at all.

    Whole words only, and exactly one distinct colour or none. `Blueberry` contains `blue`
    and `Graygreen` contains `gray`, so a substring match would get both wrong with the
    confidence of a right answer; and a title naming two colours is a two-tone case, where
    picking one is not a partial answer but a wrong one.
    """
    identity = fields.get("identity", {})
    if identity.get("color") or not vocabulary.colours:
        return {}
    found = {colours.resolve(phrase, vocabulary) for phrase in _colour_phrases(fields, vocabulary)}
    found.discard(None)
    if len(found) != 1:
        return {}
    return {"identity": {**identity, "color": found.pop()}}


def _colour_phrases(fields: dict[str, Any], vocabulary: Vocabulary) -> list[str]:
    """Every run of registry words in the title that is separated by spaces alone.

    `Titanium Silver` and `Midnight Blue` are one phrase each and resolve through `colours`
    exactly as a shop's own field would; `Black/Orange` is two, and stays two.
    """
    phrases: list[str] = []
    for chunk in _RUN.findall(fields.get("title") or ""):
        run: list[str] = []
        for word in chunk.split():
            if word.casefold() in vocabulary.colours:
                run.append(word)
                continue
            if run:
                phrases.append(" ".join(run))
            run = []
        if run:
            phrases.append(" ".join(run))
    return phrases


def without_the_maker(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """Take the maker off the front of a model that repeats it.

    Last of all, because the model is what the layers before this one worked out. Two words
    before one, so `Bang & Olufsen` and `Kruger&Matz` come off whole.
    """
    model = (fields.get("model") or "").strip()
    if not model or not vocabulary.brand_names:
        return {}
    words = model.split()
    for take in (2, 1):
        if len(words) <= take:
            continue
        maker = " ".join(words[:take])
        if maker.casefold() in vocabulary.brand_names:
            shorter = naming.without_brand(model, maker)
            return {"model": shorter} if shorter != model else {}
    return {}


def without_a_trailing_colour(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """Drop a colour the registry knows off the end of the model.

    Only off the end, only a word the registry was given, and never the last word left: a
    colour in the middle of a name is part of it, a word nobody entered is not a colour,
    and a model that is nothing but a colour word is a shop's mistake to be seen.
    """
    model = (fields.get("model") or "").strip()
    if not model or not vocabulary.colours:
        return {}
    words = model.split()
    while len(words) > 1 and words[-1].strip(",.").casefold() in vocabulary.colours:
        words = words[:-1]
    shorter = " ".join(words)
    return {"model": shorter} if shorter != model else {}


def from_the_registry(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The model as the registry spells it, found whole in the title.

    Last of all, and reading the title rather than the model the layers before this one
    cut out: a shop with no model field leaves its own spec sheet on the model — `Galaxy
    S26 S942 5G Dual Sim` — and the name is still in the title, whole. When it is not, the
    shop's own reading stands; this fills nothing in and only replaces.

    Scoped to the maker the shop stated. A shop that states none — m79's German feed — gets
    every page, and only an answer exactly one of them gives: `Note 17` under two makers is a
    question for the brand rung, not for this.

    A maker the shop stated, that the catalogue knows, and that has no page gets nothing,
    not every page. That fallback read another maker's names into this one's titles: ZTE has
    no page, Hammer's has `Blade`, and `ZTE Blade A31 lite` and `ZTE Blade A76 5G` were read
    as a Hammer model name and filed together under one entry, nine listings of four
    different phones. A stated string that is no maker we know — `Nothing Phone`, the
    reseller `Getnord`, `product` — still gets every page: there the brand field says
    nothing, and the fallback is what finds the name.
    """
    if not vocabulary.models:
        return {}
    maker = _maker_key(fields.get("brand_raw"))
    if maker in vocabulary.models:
        pages = [vocabulary.models[maker]]
    elif str(fields.get("brand_raw") or "").strip().casefold() in vocabulary.brand_names:
        return {}
    else:
        pages = list(vocabulary.models.values())
    for text in (fields.get("title"), fields.get("model")):
        if not text:
            continue
        found = {name for page in pages if (name := models.from_title(str(text), page))}
        if len(found) == 1:
            return {"model": found.pop()}
    return {}


def _maker_key(raw: Any) -> str | None:
    """The brand as the registry is keyed, or nothing — the same function the keys use."""
    if not raw:
        return None
    try:
        return normalize_brand(str(raw))
    except ValueError:
        return None


def megabytes(text: str) -> int | None:
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
    # A size the title marks as working memory is not the capacity, however alone it is:
    # m79's `… | Qualcomm | Internal RAM 12 GB | …` names no capacity at all, and read as
    # one it filed 12 phones on 25.09.2026 as 12 GB of storage. `RAM` is the industry's
    # word, the same in every language.
    text = _MARKED_RAM.sub(" ", text)
    sizes = [_size(amount, unit) for amount, unit in _SIZE.findall(text)]
    # A pair sharing one unit contributes both of its halves, not just the spelled one.
    for first, second, unit in _SHARED_UNIT.findall(text):
        sizes += [_size(first, unit), _size(second, unit)]

    believable = [size for size in sizes if size <= LARGEST_DEVICE_MB]
    return max(believable) if believable else None


_MARKED_RAM = re.compile(
    r"\bRAM\s*:?\s*\d+(?:[.,]\d+)?\s?GB\b|\b\d+(?:[.,]\d+)?\s?GB\s+(?:of\s+)?RAM\b",
    re.IGNORECASE,
)


def _size(amount: str, unit: str) -> int:
    return int(float(amount.replace(",", ".")) * SCALE[unit.upper()])
