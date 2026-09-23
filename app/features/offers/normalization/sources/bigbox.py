"""Reading what bigbox.lv's search index hands over.

Written against 984 real phones measured on 22.09.2026. Generic finds the title, the brand,
the price and the stock flag in this shape; what it cannot guess is that the barcode is
under a name it does not know, and that a field holding the maker's own code is called
nothing at all.
"""

import re
from typing import Any

from app.features.offers.normalization import colours
from app.features.offers.normalization.rules import SOURCE, Rule, Ruleset, Vocabulary, register

SLUG = "bigbox-phones"
VERSION = "bigbox-9"

# `256GB`, `1 TB`, `128 MB`. Where the model stops and the configuration begins.
SIZE = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:TB|GB|MB)\b", re.IGNORECASE)
# `4/128GB` writes the working memory and the capacity as one, and only the second half
# carries a unit — so cutting at the unit leaves `4/` behind, on the model.
_RAM_PREFIX = re.compile(r"\s*\d+\s*/\s*$")
# A diagonal is a specification, and everything after it on these titles is too.
_FROM_DIAGONAL = re.compile(
    # No word boundary after the quote mark: there is none between `"` and a space, and
    # requiring one is why this matched nothing the first time.
    r'\s*\d+(?:[.,]\d+)?\s*(?:"|\b(?:collas|inch)\b).*$',
    re.IGNORECASE,
)
_TRAILING = re.compile(r"[\s,/]+$")
# Some titles put the brand *after* the colour — `… 256GB BLACK BLACKVIEW`. Nineteen of
# them, and without this the colour is hidden behind a word that is not one.
_LAST_CAPACITY = SIZE

# Labelled by the index itself as `Tālruņa modelis`.
LINE_KEY = "Tālruņa modelis"


def _model(
    payload: dict[str, Any],
    fields: dict[str, Any],
    vocabulary: Vocabulary,
    *,
    also_cut_at: re.Pattern[str] | None = None,
    keep_diagonal: bool = False,
) -> dict[str, Any]:
    """The model, cut out of a title whose word order this shop keeps.

    `[kind] [brand] MODEL CAPACITY COLOUR`, and each step of the cut is one of those.
    """
    title = (fields.get("title") or "").strip()
    if not title:
        return {}

    words = title.split()
    at = 0
    # The words naming the category come from the registry, not from here: they are Latvian,
    # and a Lithuanian shop needs rows rather than another tuple in this module.
    while (
        at < len(words)
        and words[at].strip(',.\u201e\u201c"').casefold() in vocabulary.category_names
    ):
        at += 1

    brand = (fields.get("brand_raw") or "").strip()
    if brand and at < len(words) and words[at].casefold() == brand.casefold():
        at += 1

    rest = " ".join(words[at:])
    cuts = [m for m in (SIZE.search(rest), also_cut_at and also_cut_at.search(rest)) if m]
    found = min(cuts, key=lambda match: match.start()) if cuts else None
    if not found:
        # Nothing to cut at. On this shop that is a feature phone or a desk phone, where
        # there is no capacity to state — and the colour then runs into the name, so two
        # colours of one handset would become two products. Better a visible gap.
        return {}

    head = rest[: found.start()]
    if not keep_diagonal:
        head = _FROM_DIAGONAL.sub("", head)
    model = _TRAILING.sub("", _RAM_PREFIX.sub("", head)).strip()
    return {"model": model[:200]} if model else {}


def _color(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """Colour off the end of the title, resolved through the registry or dropped.

    This shop states no colour anywhere else, and colour is one of the two axes a phone is
    told apart by. Without it 147 of its listings reached a rung that found four candidates
    differing only in colour and refused to choose — while the listing said `Black` in its
    own title and four entries stood there, one of them black.

    Cut at the **last** capacity rather than the first: a few titles carry two, and the
    colour follows the last. Then a trailing brand comes off, because some titles close
    `BLACK BLACKVIEW` and the colour would otherwise be hidden behind a word that is not
    one. Two words are tried before one, for `Sand Dune` and `Deep Blue`.

    Measured on 985: 626 resolve. The rest is the maker's marketing — `Obsidian`,
    `Glacier`, `Moonstone` — which stays unresolved on purpose, the same refusal made
    everywhere else in this reading.
    """
    if not vocabulary.colours:
        return {}
    title = (fields.get("title") or "").strip()
    sizes = list(SIZE.finditer(title))
    tail = title[sizes[-1].end() :] if sizes else title.rsplit(",", 1)[-1]

    words = tail.strip(" ,/").split()
    brand = (fields.get("brand_raw") or "").strip()
    if brand and words and words[-1].casefold() == brand.casefold():
        words = words[:-1]

    canonical = colours.resolve(" ".join(words[-3:]), vocabulary)
    return {"identity": {**fields.get("identity", {}), "color": canonical}} if canonical else {}


def _line(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    line = (payload.get("attributes") or {}).get(LINE_KEY)
    return {"_line": str(line).strip()} if line else {}


RULESET = register(
    SOURCE,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="bigbox-model-from-title",
                layer=SOURCE,
                why=(
                    "This shop states no model anywhere, so 768 of its listings could not"
                    " start a catalogue entry. Its titles keep one word order —"
                    " `Telefons Apple iPhone 18 Pro Max 256GB Burgundy` — so the model is"
                    " what is left after the word naming the category and the brand, cut at"
                    " the first capacity. The colour needs no handling at all: it comes"
                    " after the capacity and falls off with it. Measured on all 984: 891"
                    " yield a model, and the names agree with what ksenukai states for the"
                    " same phone — `iPhone 17 Pro`, `iPhone 18 Pro Max`,"
                    " `Galaxy S26 Ultra 5G`. The other 93 have no capacity to cut at, and"
                    " every one is a feature phone or a desk phone; there the colour runs"
                    " into the name, so they are left alone rather than filed as one"
                    " product per colour. Of the 891, about 118 come out untidy — a"
                    " diagonal that ran into the name, a title with the kind of thing at the"
                    " end instead of the front. They are untidy consistently: the same"
                    " phone yields the same string, so its variants still group together"
                    " and what suffers is how the name reads rather than what it does."
                ),
                body=_model,
            ),
            Rule(
                id="bigbox-color-from-title",
                layer=SOURCE,
                why=(
                    "This shop resolved 0 colours of 985 — it publishes no colour field and"
                    " its titles were never read for one, though they end in a word the"
                    " registry already holds. The cost of that was visible in the queue:"
                    " 147 listings reached a rung that found several entries differing only"
                    " in colour and refused to choose, while the listing said `Black` in its"
                    " own title. Cut at the last capacity, drop a brand that follows the"
                    " colour, resolve through the registry or give nothing: 626 of 985."
                ),
                body=_color,
            ),
            Rule(
                id="bigbox-line",
                layer=SOURCE,
                why=(
                    "`Tālruņa modelis` is on 40.5% of these and is not the model: it holds"
                    " `Galaxy S26` for the Ultra, the Plus and the plain one alike, and"
                    " `iPhone 17e` for every capacity. Matching on it would make one"
                    " ambiguous pile out of a whole family. It is a product **line**, which"
                    " is what the layer below the brand selects on, so that is where it goes."
                ),
                body=_line,
            ),
        ),
    ),
)


# The shop titles its tablets as it titles its phones — `Planšetdators` in front where
# `Telefons` was, then brand, name and configuration — and on 23.09.2026 the phone rules
# left a model on 525 of its 580 tablets. The line rule stays behind: `Tālruņa modelis` is a
# phone's field.
TABLETS_SLUG = "bigbox-tablets"
TABLETS_VERSION = "bigbox-tablets-3"

# `8+128`, `16/512`, `8/256` — memory and storage with no unit. A tablet's title states its
# configuration that way as often as `128GB`, where a phone's that says none is a feature
# phone with nothing to state.
_PAIR = re.compile(r"\b\d{1,2}\s*[+/]\s*\d{2,4}\b")


def _tablet_model(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The phone rule, cut at a unitless pair as well: `OPPO Pad 5 8+128 5G` read no model."""
    # The diagonal is kept: on a tablet what follows it is the chip — `iPad Air 11" M4` — and
    # `iPad Air M3` and `M4` are two generations. The category's rule moves the size itself.
    return _model(payload, fields, vocabulary, also_cut_at=_PAIR, keep_diagonal=True)


TABLETS_RULESET = register(
    SOURCE,
    TABLETS_SLUG,
    Ruleset(
        version=TABLETS_VERSION,
        rules=(
            Rule(
                id="bigbox-tablets-model-from-title",
                layer=SOURCE,
                why=(
                    "bigbox's phone model rule: the kind word off the front, the cut at the"
                    " configuration. 525 of 580 tablets read a model with it unchanged; the"
                    " screen size it cuts away is put back by the tablet category's rule."
                    " The configuration is also cut at a pair with no unit, `8+128` or"
                    " `16/512`: the phone rule reads a title with no capacity as a feature"
                    " phone and leaves the model empty, and nine tablets were read that way."
                ),
                body=_tablet_model,
            ),
            Rule(
                id="bigbox-tablets-color-from-title",
                layer=SOURCE,
                why="bigbox's colour, read the way its phones' is.",
                body=_color,
            ),
        ),
    ),
)
