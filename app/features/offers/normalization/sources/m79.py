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

from app.features.offers.normalization import barcodes
from app.features.offers.normalization.rules import (
    SOURCE,
    Rule,
    Ruleset,
    Vocabulary,
    register,
)

SLUG = "m79-phones"
VERSION = "m79-3"

# Both of the shop's words mean it can be bought. `Ir noliktavā` is the warehouse and
# `Ir veikalā` the shop floor — a difference in where it sits, not in whether it is there.
IN_STOCK = ("Ir noliktavā", "Ir veikalā")

# The shop's own join id, which names a row in its import and nothing in the world. 1837 of
# the 2700 codes are one, and putting one on `mpn` would be a part number that can never
# agree with another shop's.
INTERNAL = "JOINEDIT"

# `256GB`, `512 GB`, `16 Gt`. The plain way to write the configuration.
SIZE = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:TB|GB|MB|Gt)\b", re.IGNORECASE)
# `8/128GB`, `512/16 Gt`, `12/512` — memory and capacity joined by a slash, with the unit on
# one end or missing. The capacity pattern finds `128GB` inside `8/128GB`, which is the
# middle of the configuration rather than its start, so the earliest match has to win.
SLASH = re.compile(r"\b\d{1,4}\s*/\s*\d{1,4}(?:\s?(?:TB|GB|MB|Gt))?\b", re.IGNORECASE)
# `(6932554496944)`, `(Enterprise Edition)`. A shop's parenthesis is never part of a model.
_BRACKETED = re.compile(r"[(\[][^)\]]*[)\]]")
_EDGES = re.compile(r"^[\s,./|-]+|[\s,./|-]+$")


def _barcode(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    return {"gtin": barcodes.pick(payload.get("barcodes"))}


def _part_number(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The shop's item code, when it is the maker's and not the shop's own."""
    code = str(payload.get("code") or "").strip()
    if not code or code.upper().startswith(INTERNAL):
        return {}
    # A code that is the barcode is already recorded as one. Recording it twice would put a
    # barcode on the part number rung, where it would match things a barcode never would.
    if code == fields.get("gtin") or code.isdigit():
        return {}
    return {"mpn": code[:100]}


def _availability(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    flag = str(payload.get("availability") or "").strip()
    return {"availability": "in_stock"} if flag in IN_STOCK else {}


def _model(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The name, with the kind stripped off both ends and the configuration cut away."""
    title = str(fields.get("title") or payload.get("name") or "")
    if not title:
        return {}

    # The first comma ends the name and begins the datasheet on the feed's records:
    # `Xiaomi Redmi 17, 17,8 cm (6.99), 1600 x 720 Pixel, 4 GB, …`. The shop's own records
    # carry no comma before the configuration, so this costs them nothing.
    head = _BRACKETED.sub(" ", title).split(",", 1)[0]
    # The earliest of the two, not the first one tried: on `A57 5G 8/128GB` the capacity
    # pattern matches `128GB`, and cutting there leaves `A57 5G 8` — one entry per memory
    # size, which is the mistake this shop's titles invite.
    found = [match for match in (SIZE.search(head), SLASH.search(head)) if match]
    if found:
        head = head[: min(found, key=lambda match: match.start()).start()]

    words = [word for word in head.split() if word]
    words = _without_kind(words, vocabulary)
    brand = (fields.get("brand_raw") or "").strip()
    if brand and words and words[0].casefold() == brand.casefold():
        words = words[1:]

    model = _EDGES.sub("", " ".join(words))
    return {"model": model[:200]} if model else {}


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
                id="m79-barcode",
                layer=SOURCE,
                why=(
                    "There is no barcode field on this shop anywhere — not on the card, not"
                    " on the product page. What there is is the address:"
                    " `…-smf966bzsbeue-8806097423720-joinedit96318361`. The channel hands"
                    " the digit runs over as a list and `barcodes.pick` chooses, as it does"
                    " for every shop, and on 2700 collected products that yields a valid"
                    " code for 1947 of them — 72%, higher than all but two of the other"
                    " ten. The number in the image address is **not** it: on 34 sampled"
                    " cards it was 13 digits once and the shop's own id the other 33 times,"
                    " which is why the channel does not collect it."
                ),
                body=_barcode,
            ),
            Rule(
                id="m79-part-number",
                layer=SOURCE,
                why=(
                    "`data-itemid` is base64 and the channel decodes it, but what comes out"
                    " is three different things depending on the supplier: Samsung's"
                    " `SM-A576BZABEUE`, Spigen's `ACS04816`, a bare barcode, or the shop's"
                    " own `JOINEDIT96318361`. The last is 1837 of the 2700 and names a row"
                    " in this shop's import rather than anything in the world — on `mpn` it"
                    " would be a part number that can never agree with another shop's, and"
                    " the part number rung would gain 1837 dead ends. Digits are dropped"
                    " for the opposite reason: they are already the barcode, and the same"
                    " value on two rungs makes the weaker one look as strong as the"
                    " stronger. What is left is 743 real part numbers."
                ),
                body=_part_number,
            ),
            Rule(
                id="m79-availability",
                layer=SOURCE,
                why=(
                    "Two words and no third: `Ir noliktavā` on 2667 of 2700 and `Ir veikalā`"
                    " on 33. Both mean it can be bought — one is the warehouse and the other"
                    " the shop floor — so this shop states where a thing is rather than"
                    " whether it is there. It publishes nothing it has not got, which is why"
                    " there is no out-of-stock word to read; if one ever appears it will"
                    " read as `unknown` and be visible, which is the right way round."
                ),
                body=_availability,
            ),
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
                    " catalogue entry named after one groups with nothing. Then the cut at"
                    " the configuration, the same as every other shop here, with `Gt` beside"
                    " `GB` because the Finnish feed writes it that way — and at the"
                    " **earliest** of the two forms, not the first one tried. This shop"
                    " writes `8/128GB` as often as `128GB`, the capacity pattern matches the"
                    " `128GB` inside it, and cutting there leaves `Galaxy A57 5G 8`: one"
                    " catalogue entry per memory size."
                    "\n\n"
                    "And the first comma ends it, because on the feed's records the"
                    " datasheet begins there: `Xiaomi Redmi 17, 17,8 cm (6.99), 1600 x 720"
                    " Pixel, 4 GB, …` is one product and `Xiaomi Redmi 17` is its name. The"
                    " shop's own records put no comma before the configuration, so they"
                    " lose nothing to it."
                ),
                body=_model,
            ),
        ),
    ),
)
