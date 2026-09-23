"""Reading what dateks.lv's pages hand over.

Written against 745 real phones collected on 22.09.2026. Generic already finds the title,
the brand, the price and the manufacturer code here — the channel hands all four over under
the names it looks for — so this module is the four things it cannot know: which of the
codes on a card is a barcode, what the shop's Latvian stock words are worth, where the model
ends, and that the colour is the last thing in the name.
"""

import re
from typing import Any

from app.features.offers.normalization import colours, naming
from app.features.offers.normalization.rules import (
    SOURCE,
    Rule,
    Ruleset,
    Vocabulary,
    register,
)

SLUG = "dateks-phones"
VERSION = "dateks-5"


# `256GB`, `1 TB`, `128 MB`. Where the model stops and the configuration begins, for the
# few names that run them together instead of separating them with a comma.
SIZE = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:TB|GB|MB)\b", re.IGNORECASE)
# `10C/4/128GB` writes the working memory and the capacity as one, so cutting at the unit
# leaves `10C/4/` behind, on the model.
_RAM_PREFIX = re.compile(r"\s*\d+\s*/\s*$")
_TRAILING = re.compile(r"[\s,/-]+$")


def _model(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The model, cut out of the name in front of the first comma.

    The name is `BRAND MODEL, RAM/CAPACITY, COLOUR` and the shop keeps that shape, so the
    comma is the cut and the brand comes off the front. What is left is the model with no
    configuration and no colour in it.
    """
    name = (payload.get("name") or "").strip()
    if not name:
        return {}

    head = naming.without_brand(name.split(",")[0].strip(), payload.get("brand") or "")

    # A name with no comma at all is a supplier's description the shop pasted whole —
    # `S26 Ultra 5G EE 256GB Black Android`. Cutting at the capacity saves the model out of
    # it; without that the configuration travels as part of the model and splits one phone
    # into one product per capacity.
    found = SIZE.search(head)
    if found:
        head = _RAM_PREFIX.sub("", head[: found.start()])

    model = _TRAILING.sub("", head).strip()
    return {"model": model[:200]} if model else {}


def _color(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """Colour out of the one place this shop always puts it: the end of the name.

    Not the loose "cut a colour out of a title" this project refuses elsewhere — the shape
    is fixed and the shop keeps it. Everything is resolved through the registry, so a word
    the registry does not know produces nothing rather than a guess.
    """
    if not vocabulary.colours:
        return {}
    parts = [part.strip() for part in str(payload.get("name") or "").split(",")]
    if len(parts) < 2:
        return {}

    # Backwards, and never as far as the first segment, which is the model. Stepping back
    # is what reads `…, Yellow, No Charger`: the shop appends what it wants after the
    # colour and the colour is still the last thing that is one.
    for segment in reversed(parts[1:]):
        found = (
            colours.pair([half.strip() for half in segment.split("/")], vocabulary)
            if "/" in segment
            else colours.resolve(segment, vocabulary)
        )
        if found:
            return {"identity": {**fields.get("identity", {}), "color": found}}
    return {}


RULESET = register(
    SOURCE,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="dateks-model",
                layer=SOURCE,
                why=(
                    "Nothing in this shop states a model, so all 745 listings read with no"
                    " model at all and none of them could start a catalogue entry. The name"
                    " is `BRAND MODEL, RAM/CAPACITY, COLOUR` — 660 of 745 carry two commas"
                    " and 63 carry one — so the first comma is the cut and the brand, which"
                    " this shop leaves on the front unlike rdveikals, comes off. Measured:"
                    " 745 of 745 yield a model and they collapse to 269 distinct ones, which"
                    " is the shape expected of a category whose phones come in several"
                    " colours and capacities each. The 17 names with no comma are a"
                    " supplier's description pasted whole and are cut at the capacity"
                    " instead; without that step 4 of them carried `256GB` into the model."
                ),
                body=_model,
            ),
            Rule(
                id="dateks-colour",
                layer=SOURCE,
                why=(
                    "The category's own rules find a colour on 530 of 745 from the"
                    " specification table, and the name has it for most of the rest: reading"
                    " the last comma-separated segment through the registry brings the total"
                    " to 725 (97.3%). The walk is backwards over the segments rather than"
                    " straight at the last one because the shop appends its own notes after"
                    " the colour — `…, Yellow, No Charger` — and a two-tone case is written"
                    " `Black/Orange`, which is its own value and its own product. The 20"
                    " that stay unread are a maker's marketing that the registry has not"
                    " been taught — `PANTONE Titan`, `Awesome Charcoal`, `Starlight` — and"
                    " they are left visible rather than guessed at: a colour mapped wrongly"
                    " splits one product into several, confidently."
                ),
                body=_color,
            ),
        ),
    ),
)


# The tablets are the same pages under `/cenas/plansetdatori`, and the name keeps the phones'
# shape — `Samsung Galaxy Tab S10 FE, 8GB/128GB, Blue` — so both of its rules read them as
# they are. Measured on the 402 collected on 23.09.2026: a model for 402 and a colour, with
# the category's own, for 380.
TABLETS_SLUG = "dateks-tablets"
TABLETS_VERSION = "dateks-tablets-1"

TABLETS_RULESET = register(
    SOURCE,
    TABLETS_SLUG,
    Ruleset(
        version=TABLETS_VERSION,
        rules=(
            Rule(
                id="dateks-tablets-model",
                layer=SOURCE,
                why=(
                    "The phones' cut at the first comma, on the same name. 402 of 402 tablets"
                    " read a model with it; the connectivity words and the screen that some"
                    " heads carry are the tablet category's to take off."
                ),
                body=_model,
            ),
            Rule(
                id="dateks-tablets-colour",
                layer=SOURCE,
                why="The name ends in the colour, as for the phones: `…, Luna Grey`.",
                body=_color,
            ),
        ),
    ),
)
