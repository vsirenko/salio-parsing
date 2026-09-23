"""What a phone listing means, whichever shop it came from.

Written against 520 real phones collected on 21.09.2026. Everything here is about the kind
of product rather than about a shop: where a shop hides its storage figure is a source
rule, but that storage is what tells two otherwise identical phones apart is true of every
shop that sells them.
"""

import re
from typing import Any

from app.features.brands.normalization import normalize_brand
from app.features.offers.normalization import colours, models, naming
from app.features.offers.normalization.rules import (
    CATEGORY,
    FINISH,
    Rule,
    Ruleset,
    Vocabulary,
    register,
)

SLUG = "phones"
# Bumped when a rule body changes, not only when a rule is added: the version is
# what a reparse compares to decide whether a stored reading is stale, so a fix
# that leaves it alone is a fix that never reaches the rows it was written for.
VERSION = "phones-11"

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


# Words separated by spaces alone. Anything else between them — a slash, a comma, a bar —
# is the shop separating two colours, and joining those is how `black/orange` becomes
# `orange`: not a partial answer but a wrong one.
_RUN = re.compile(r"[^\W\d_]+(?:[ \t]+[^\W\d_]+)*", re.UNICODE)


def _color_from_title(
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


def _without_the_maker(
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


def _without_a_trailing_colour(
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


def _from_the_registry(
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
            Rule(
                id="phones-color-from-title",
                layer=CATEGORY,
                why=(
                    "The rule above reads a field and never a title, and that stands: cut"
                    " from a title the word takes 358 forms across one shop's products, and"
                    " canonicalising those by guessing splits one product into several."
                    " This is not that. It asks whether the title contains a word the"
                    " registry has **already been given an answer for** — which is a lookup,"
                    " not a guess — and a word nobody entered produces nothing."
                    "\n\n"
                    "Measured before it was written. Where a shop states a colour in a field"
                    " as well, the title word agrees on 4988 readings and disagrees on 320,"
                    " and the disagreements are granularity rather than contradiction:"
                    " burgundy against red, mint against green, navy against blue, graphite"
                    " against grey. Checked again on m79.lv alone, which states a field on"
                    " 15% of its cards: 222 agree, 18 disagree, and 11 of those 18 are a"
                    " two-tone field the title wrote as one colour. None of it fires in"
                    " practice, because this only runs where the field gave nothing."
                    "\n\n"
                    "What it is worth: 1547 of m79's 2390 colourless listings get a colour,"
                    " almost all of them a plain word a shop wrote in its own title —"
                    " `black` 426, `blue` 209, `white` 110, `orange` 91, `silver` 85. Those"
                    " listings carry no barcode either, and colour is the axis that was"
                    " keeping them from becoming a catalogue entry."
                    "\n\n"
                    "Words side by side are one phrase, not two colours. `Titanium Silver`,"
                    " `Midnight Blue` and `Glacier Blue` all carry two entries the registry"
                    " knows, and counting distinct values refused every one of them: 130"
                    " listings, of which 99 are a single phrase and only 31 name two"
                    " colours. A run is broken by anything but a space, because a shop"
                    " writing `Black/Orange` means both — and joining those is how"
                    " `black/orange` becomes `orange`, which is not a partial answer but a"
                    " wrong one."
                    "\n\n"
                    "One known cost. A maker's palette lives in the brand layer, which runs"
                    " after this, and a palette only fills a colour that is missing — so on"
                    " a title carrying both a registry word and a maker's name for the same"
                    " colour, the coarser answer wins: `Titanium Jadegreen` reads as"
                    " `titanium` rather than green. Nineteen listings in the corpus, all"
                    " Samsung's `Titanium` line, and `titanium` is a material the registry"
                    " calls a colour — which is the thing to fix, rather than this."
                ),
                body=_color_from_title,
            ),
            Rule(
                id="phones-model-does-not-repeat-the-maker",
                layer=FINISH,
                why=(
                    "`Motorola Motorola G06 Power` is how a catalogue entry came out, and"
                    " 301 of 2939 of them read that way: the title composes the brand and"
                    " the model, and the model already held the brand. It gets there because"
                    " a shop that states no maker in a field leaves it at the front of the"
                    " name, and the shop's own rule can only cut off a brand the shop"
                    " stated. 1821 of m79's 2680 models repeat the maker, and euronics,"
                    " discover, bm, rdveikals and dateks all do it too."
                    "\n\n"
                    "Which word is the maker is not something a rule can know and not"
                    " something the shop says, so the names are handed in as vocabulary —"
                    " the same way the words for `phone` are. A catalogue with no brands in"
                    " it yet hands in nothing and this does nothing, which is the right"
                    " behaviour rather than a gap."
                    "\n\n"
                    "Last of all, because the model is what every layer before this one"
                    " worked out. Through `naming.without_brand` so the cut respects a word"
                    " boundary: `CAT` against `Caterpillar CAT S75` once cut mid-word."
                ),
                body=_without_the_maker,
            ),
            Rule(
                id="phones-model-without-a-trailing-colour",
                layer=FINISH,
                why=(
                    "`Cat S31 Black`, `Nokia 106 Black`, `Galaxy S10 Lite Grey`: a title with no"
                    " capacity in it gives a shop's subtraction nothing to cut at, and the"
                    " colour stays on the model — one catalogue entry per colour, named after"
                    " one of them. Five listings on 22.09.2026, four at bm and one at"
                    " rdveikals, and the colour itself had already been read correctly off the"
                    " same title. m79 does this in its own rules; it belongs to every shop."
                    "\n\n"
                    "The words are the registry's colours, handed in, so no shop's or"
                    " language's words live here. Only off the end and never the last word:"
                    " a colour in the middle of a name is part of the name."
                ),
                body=_without_a_trailing_colour,
            ),
            Rule(
                id="phones-model-from-the-registry",
                layer=FINISH,
                why=(
                    "211 of 1524 catalogue entries were named `Galaxy S26 S942 5G Dual Sim`,"
                    " `razr fold 20.6 cm Dual SIM Android 16.0` and the like, 170 of them by"
                    " the two shops that publish no model field. Their rules cut the model"
                    " out of the title by subtraction — everything before the first capacity"
                    " — and subtraction cannot be made clean, because the list of what to cut"
                    " is open: `5G`, `Dual Sim`, `Hybrid Dual SIM`, `USB Type-C`, `17.3 cm`,"
                    " an internal code, a German `Interner Speicher`. Every rule closes one"
                    " tail and the next shop opens another."
                    "\n\n"
                    "Recognition is closed: a title holds a name the registry knows or it"
                    " does not. Measured against the 845 spellings the eight clean shops"
                    " read, a known name sits whole in 77% of bm's titles and 88% of m79's,"
                    " where the model those shops' own rules read agrees with the rest of"
                    " the market on 21% and 26%. The name was there all along."
                    "\n\n"
                    "Which words are a model is the same kind of fact as which words are a"
                    " colour, so it is rows — `model_aliases`, per maker — handed in as"
                    " vocabulary, and this holds only the matching: whole words, longest"
                    " wins, two different names decide nothing. The registry cannot be"
                    " derived from the catalogue it is meant to clean: `Galaxy S26 S942 5G"
                    " Dual Sim` is in the title too, and as the longest known name it would"
                    " win. It is seeded from the shops that read cleanly and grown by hand."
                    "\n\n"
                    "A title holding no known name keeps what the shop's rule cut out. The"
                    " tail is a shop selling what nobody else sells — Nubia, Blackview,"
                    " ZTE — and a spelling the registry has not been told: `Samsung S26`"
                    " without its `Galaxy`. Both are rows, not rules."
                ),
                body=_from_the_registry,
            ),
        ),
    ),
)
