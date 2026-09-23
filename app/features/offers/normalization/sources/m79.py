"""Reading what m79.lv's listing cards hand over.

Written against 2700 real products collected on 22.09.2026. Generic already finds the title
and the price — the channel hands both over under the names it looks for — and the category
finds the capacity in 96% of the titles. What is left is the four things neither can know:
which of the numbers on a card is a barcode, which is a part number rather than the shop's
own join id, what the two Latvian stock words are worth, and where the model ends.

## One shop, several suppliers, several languages

This shop resells feeds and does not rewrite them. A title arrives as `Smartfon Samsung
Galaxy S25 Ultra 5G 12/512GB Czarny` in Polish, `OPPO Find X9 Pro 5G puhelin, 512/16 Gt` in
Finnish, `Samsung EF-XF976 Beskyttelsescover` in Danish — and the shop appends `Mobilais
Telefons` to every one of them, whatever it is. So the words that are not the model sit at
both ends of the title, and they belong to no single language.

That is why the model rule strips them through `vocabulary.category_names` rather than from a
list here. `mobilais`, `telefons`, `smartphone` and `mobile` are already registry rows and
this shop needs `smartfon` and `puhelin` beside them — which is a row somebody enters, not a
line somebody writes. A word the registry has not been given stays on the model, visibly.
"""

import re
from typing import Any

from app.features.offers.normalization.rules import (
    SOURCE,
    Rule,
    Ruleset,
    Vocabulary,
    register,
)

SLUG = "m79-phones"
VERSION = "m79-8"


# `256GB`, `512 GB`, `16 Gt`. The plain way to write the configuration.
SIZE = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:TB|GB|MB|Gt)\b", re.IGNORECASE)
# `8/128GB`, `512/16 Gt`, `6+128GB` — memory and capacity joined by a slash or a plus, unit on
# one end or missing. The capacity pattern finds `128GB` inside `8/128GB`, which is the
# middle of the configuration rather than its start, so the earliest match has to win.
SLASH = re.compile(r"\b\d{1,4}\s*/\s*\d{1,4}(?:\s?(?:TB|GB|MB|Gt))?\b", re.IGNORECASE)
# `(6932554496944)`, `(Enterprise Edition)`. A shop's parenthesis is not part of a model —
# with one exception, `_BRACKETED_PLUS`, taken out first.
_BRACKETED = re.compile(r"[(\[][^)\]]*[)\]]")
# `Ulefone Armor 34 (Plus)`: the maker's own variant word, bracketed by one supplier. Cut
# away with the rest it filed the plus phone under the plain one.
_BRACKETED_PLUS = re.compile(r"[(\[]\s*(?:plus|\+)\s*[)\]]", re.IGNORECASE)
# Where the name ends and the datasheet begins. This shop's feeds use four separators and no
# two suppliers use the same one, so all four are tried and the earliest wins.
_COMMA = re.compile(r",")
_PIPE = re.compile(r"\s*\|")
# A spaced dash, never a hyphen inside a code: `XT2607-1` and `SM-A576B` keep theirs.
_DASH = re.compile(r"\s+-\s+")
# `17.2 cm`, `6.78"`, `16,7cm`. The screen is the first thing every datasheet states, and it
# is what was leaving `Nothing 4a 17.2 cm Dual SIM Android 16.0` as a model.
_SCREEN = re.compile(r"\b\d{1,2}[.,]?\d*\s*(?:cm|inch|”|\"|\'\')", re.IGNORECASE)
_EDGES = re.compile(r"^[\s,./|-]+|[\s,./|-]+$")


def _model(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The name, with the kind stripped off both ends and the configuration cut away."""
    title = str(fields.get("title") or payload.get("name") or "")
    if not title:
        return {}

    head = _BRACKETED.sub(" ", _BRACKETED_PLUS.sub(" Plus ", title))
    # The earliest of them all, not the first one tried: on `A57 5G 8/128GB` the capacity
    # pattern matches `128GB`, which is the middle of the configuration rather than its
    # start, and cutting there leaves `A57 5G 8` — one entry per memory size.
    found = [
        match
        for match in (
            SIZE.search(head),
            SLASH.search(head),
            _COMMA.search(head),
            _PIPE.search(head),
            _DASH.search(head),
            _SCREEN.search(head),
        )
        if match
    ]
    if found:
        head = head[: min(found, key=lambda match: match.start()).start()]

    words = [word for word in head.split() if word]
    words = _without_kind(words, vocabulary)
    brand = (fields.get("brand_raw") or "").strip()
    if brand and words and words[0].casefold() == brand.casefold():
        words = words[1:]

    words = _without_colour(words, vocabulary)
    model = _EDGES.sub("", " ".join(words))
    return {"model": model[:200]} if model else {}


def _without_colour(words: list[str], vocabulary: Vocabulary) -> list[str]:
    """Drop a colour the registry knows off the end of the name.

    `Leva L10 graphite`, `Redmi 15C Mint Green`, `Halo 3 Black` — a name with no capacity in
    it has nothing to cut at, so the colour stays and one product becomes one entry per
    colour. Only off the end, and only a word the registry was given: a colour in the middle
    of a name is part of it, and a word nobody entered is not a colour.
    """
    if not vocabulary.colours:
        return words
    while len(words) > 1 and words[-1].strip(",.").casefold() in vocabulary.colours:
        words = words[:-1]
    return words


def _without_kind(words: list[str], vocabulary: Vocabulary) -> list[str]:
    """Drop the words for `phone` off both ends, however many and whichever language.

    Both ends because this shop puts them at both: a supplier's `Smartfon` in front and the
    shop's own `Mobilais Telefons` behind. Through the registry rather than a list here —
    the same word is a Latvian fact at one supplier and a Polish one at the next.
    """
    if not vocabulary.category_names:
        return words
    known = lambda word: word.strip(",.").casefold() in vocabulary.category_names  # noqa: E731
    start, end = 0, len(words)
    while start < end and known(words[start]):
        start += 1
    while end > start and known(words[end - 1]):
        end -= 1
    return words[start:end]


RULESET = register(
    SOURCE,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="m79-model",
                layer=SOURCE,
                why=(
                    "This shop resells feeds without rewriting them, so the words that are"
                    " not the model arrive at both ends of the title and in several"
                    " languages: `Smartfon` in front from a Polish supplier, `puhelin` from"
                    " a Finnish one, and `Mobilais Telefons` behind from the shop itself, on"
                    " every product including the cables. Both ends are therefore stripped,"
                    " and through `vocabulary.category_names` rather than a list here —"
                    " `mobilais`, `telefons`, `smartphone` and `mobile` are registry rows"
                    " already, and `smartfon` and `puhelin` are rows somebody enters rather"
                    " than lines somebody writes. A word the registry has not been given"
                    " stays on the model, where it is visible."
                    "\n\n"
                    "Then the brackets, because this shop puts the barcode in them —"
                    " `Samsung Galaxy A57 5G 8GB/128GB Navy (8806099028282)` — and a"
                    " catalogue entry named after one groups with nothing. All but one: a"
                    " bracket holding nothing but `Plus` is the maker's variant word, and"
                    " `Armor 34 (Plus)` and `Armor 34 Pro (Plus)` — two of the 2700, the only"
                    " bracketed plus this shop has — were filed under the plain phones"
                    " because of it. Then the cut at"
                    " the configuration, the same as every other shop here, with `Gt` beside"
                    " `GB` because the Finnish feed writes it that way — and at the"
                    " **earliest** of the two forms, not the first one tried. This shop"
                    " writes `8/128GB` as often as `128GB`, the capacity pattern matches the"
                    " `128GB` inside it, and cutting there leaves `Galaxy A57 5G 8`: one"
                    " catalogue entry per memory size."
                    "\n\n"
                    "And four separators end it, because no two of this shop's suppliers"
                    " use the same one: a comma (`Xiaomi Redmi 17, 17,8 cm (6.99), …`), a"
                    " pipe (`Apple iPhone 16 Plus | White | 6.7 | Super Retina XDR | …`), a"
                    " spaced dash (`Apple iPhone 16e - 5G Smartphone - Dual-SIM - …`) and"
                    " the screen size, which every datasheet states first and which was"
                    " leaving `Nothing 4a 17.2 cm Dual SIM Android 16.0` standing as a"
                    " model. A spaced dash only, so `XT2607-1` and `SM-A576B` keep theirs."
                    " Measured over the 2700: models longer than 45 characters went from 271"
                    " to 66 and the average length from 32 to 24."
                    "\n\n"
                    "Then a colour off the end, through the registry. A name with no"
                    " capacity in it has nothing to cut at, so `Leva L10 graphite` and"
                    " `Halo 3 Black` kept theirs and became one entry per colour. Only off"
                    " the end and only a word the registry was given: a colour in the middle"
                    " of a name is part of the name."
                ),
                body=_model,
            ),
        ),
    ),
)


# The same shop writes its tablets' names exactly as it writes its phones': a supplier's
# kind word in front, `Planšetdators` behind where `Mobilais Telefons` was, the configuration
# after the name. Measured on 23.09.2026, the phone model rule read a model for 1081 of 1089
# tablets. So the tablet channel runs the same body, under a ruleset of its own — which of
# a shop's rules a category needs is the category's question, and the answer may part ways.
TABLETS_SLUG = "m79-tablets"
TABLETS_VERSION = "m79-tablets-1"

TABLETS_RULESET = register(
    SOURCE,
    TABLETS_SLUG,
    Ruleset(
        version=TABLETS_VERSION,
        rules=(
            Rule(
                id="m79-tablets-model",
                layer=SOURCE,
                why=(
                    "m79's model rule, the one its phones use: the kind words through the"
                    " registry at both ends, the brackets, the cut at the configuration and"
                    " at the four separators its suppliers use. It left a model on 1081 of"
                    " 1089 tablets without a line changed."
                ),
                body=_model,
            ),
        ),
    ),
)
