"""Reading what rdveikals.lv's pages hand over.

Written against 1396 real phones collected on 22.09.2026. What generic finds here is
already most of it — the barcode is under `ean`, the price and the stock word are where it
looks — so this module exists for the two things it cannot know: where the model is, and
that the field the shop calls a model is not one.
"""

import re
from typing import Any

from app.features.offers.normalization.devices import STORAGE_KEY, megabytes
from app.features.offers.normalization.rules import SOURCE, Rule, Ruleset, Vocabulary, register

SLUG = "rdveikals-phones"
VERSION = "rdveikals-6"

# `256GB`, `1 TB`, `128 MB`. Where the model stops and the configuration begins.
SIZE = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:TB|GB|MB)\b", re.IGNORECASE)
# `16/ 512GB` writes the working memory and the capacity as one and only the second half
# carries a unit, so cutting at the unit leaves `16/` behind, on the model.
_RAM_PREFIX = re.compile(r"\s*\d+\s*/\s*$")
_TRAILING = re.compile(r"[\s,/]+$")
# `(paraugs)`, `(ENG)`, `(no charger)`, `(without charger)` — what the shop adds after
# the colour, and what would otherwise hide it.
_MARGINALIA = re.compile(r"\s*\([^)]*\)\s*$")

# The shop's own name for the family. Labelled by the site as `Viedtālruņa modelis`.
LINE_KEY = "Kopējie parametri / Viedtālruņa modelis"


def _model(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The model, cut out of the name the shop's own analytics records.

    `name` is `MODEL RAM/CAPACITY COLOUR` with the brand and the word for the category
    already off the front — which is why this rule is three lines where the same job on a
    shop that only publishes a title takes a vocabulary of Latvian words to do.
    """
    name = (payload.get("name") or "").strip()
    if not name:
        return {}

    found = SIZE.search(name)
    if found:
        model = _TRAILING.sub("", _RAM_PREFIX.sub("", name[: found.start()])).strip()
        return {"model": model[:200]} if model else {}

    # No capacity to cut at: a feature phone or a desk phone, where the colour runs into
    # the name — `GL695 Black`. Cutting the colour off instead needs to know the word is a
    # colour, which is what the registry is for; 223 of the 241 such names on this shop end
    # in one. Without the vocabulary this stays a visible gap rather than a guess, because
    # dropping a last word that is not a colour renames the phone.
    model = _without_colour(name, vocabulary)
    return {"model": model[:200]} if model else {}


def _without_colour(name: str, vocabulary: Vocabulary) -> str:
    """The name with a trailing colour taken off, or nothing if it does not end in one.

    Two words before one, because `Sand Dune` and `Deep Blue` are colours the registry
    knows as a pair. What follows the colour is the shop's own marginalia — `(paraugs)`,
    `(ENG)`, `(no charger)` — and is dropped first so that it does not hide the colour
    behind it.
    """
    if not vocabulary.colours:
        return ""
    cleaned = _MARGINALIA.sub("", name).strip(" ,/")
    words = cleaned.split()
    for take in (2, 1):
        if len(words) > take and " ".join(words[-take:]).casefold() in vocabulary.colours:
            return _TRAILING.sub("", " ".join(words[:-take])).strip()
    return ""


def _line(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    line = (payload.get("specs") or {}).get(LINE_KEY)
    return {"_line": str(line).strip()} if line else {}


RULESET = register(
    SOURCE,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="rdveikals-model-from-name",
                layer=SOURCE,
                why=(
                    "This shop states no model in any field, so none of its 1396 listings"
                    " could start a catalogue entry — 793 of them sat in the queue carrying"
                    " a barcode nobody else had. What it does publish is the name its own"
                    " analytics block records, `Kingkong Power 5 6/ 128GB Black`, which is"
                    " the model, the configuration and the colour in that order with the"
                    " brand already removed. Cutting at the first capacity leaves the model"
                    " and takes the colour with it. Measured on all 1396: 1153 (82.6%) carry"
                    " a capacity to cut at. The other 243 have none, and every one is a"
                    " feature phone or a desk phone where the colour runs into the name"
                    " (`GL695 Black`); they are left alone rather than filed as one product"
                    " per colour, and they still match by barcode."
                ),
                body=_model,
            ),
            Rule(
                id="rdveikals-line",
                layer=SOURCE,
                why=(
                    "`Viedtālruņa modelis` is on 60.7% of these and is not the model, for"
                    " the same reason bigbox's `Tālruņa modelis` is not: it holds"
                    " `Google Pixel` for 27 different phones and `Galaxy S25 Ultra` for 18."
                    " It is a product **line**, which is what the layer below the brand"
                    " selects on, so that is where it goes. Matching on it would make one"
                    " ambiguous pile out of a whole family."
                ),
                body=_line,
            ),
        ),
    ),
)


# The tablets are the same pages under another category, and their analytics name has the
# phones' shape: `Redmi Pad 2 11" 6GB 128GB Graphite Gray`, the brand already off the front.
# Cutting at the first capacity gave a model on 581 of 584 collected on 23.09.2026, against
# none without a rule of this channel's own; the size and the connectivity words are the
# tablet category's to take off and put back.
TABLETS_SLUG = "rdveikals-tablets"
TABLETS_VERSION = "rdveikals-tablets-1"

# `16GB 512SSD`, `32GB 1TBSSD`, `16GB 1SSD`: the drive of a tablet that is a computer, written
# with no unit of its own, so the only size a title reader finds is the working memory.
_DRIVE = re.compile(r"\b\d+\s?(?:TB|GB)?SSD\b", re.IGNORECASE)


def _storage_beside_a_drive(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The stated capacity alone, where the name's only capacity is the working memory."""
    if not _DRIVE.search(str(payload.get("name") or "")):
        return {}
    stated = {
        size
        for name, value in (fields.get("attributes") or {}).items()
        if vocabulary.attribute_key(str(name)) == STORAGE_KEY
        and (size := megabytes(str(value))) is not None
    }
    if len(stated) != 1:
        return {}
    return {"identity": {**fields.get("identity", {}), STORAGE_KEY: stated.pop()}}


TABLETS_RULESET = register(
    SOURCE,
    TABLETS_SLUG,
    Ruleset(
        version=TABLETS_VERSION,
        rules=(
            Rule(
                id="rdveikals-tablets-model-from-name",
                layer=SOURCE,
                why=(
                    "The phones' cut, on the same analytics name: the model, the"
                    " configuration and the colour, in that order. 581 of 584 tablets carry"
                    " a capacity to cut at; the three that do not are left without a model."
                ),
                body=_model,
            ),
            Rule(
                id="rdveikals-tablets-storage-beside-a-drive",
                layer=SOURCE,
                why=(
                    'The shop names a tablet that is a computer `Surface Pro 11 13" X1E-80-100'
                    " 16GB 512SSD`: the drive has no unit, so the title's one capacity is the"
                    " working memory, it disagrees with `Iekšējās atmiņas apjoms` and the"
                    " category's rule rightly takes neither. 40 of 584 on 23.09.2026, 37 of"
                    " them Surfaces, left without storage for it. With `SSD` in the name the"
                    " field is the only statement of the drive, and it is taken."
                ),
                body=_storage_beside_a_drive,
            ),
        ),
    ),
)
