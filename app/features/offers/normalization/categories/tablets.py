"""What a tablet listing means, whichever shop it came from.

Written against 1089 of m79's tablets collected on 23.09.2026. Most of what a tablet is
it shares with a phone — storage and colour tell two of one model apart, the model is the
registry's name found whole in the title — and those bodies are `devices.py`'s. What is a
tablet's own is the third axis: a Wi-Fi tablet and its cellular twin are two products with
two barcodes and two prices, and a shop writes which it is into the name.
"""

import re
from typing import Any

from app.features.offers.normalization import devices
from app.features.offers.normalization.rules import (
    CATEGORY,
    FINISH,
    Rule,
    Ruleset,
    Vocabulary,
    register,
)

SLUG = "tablets"
VERSION = "tablets-7"

CONNECTIVITY_KEY = "connectivity"
SCREEN_KEY = "screen_inch"
# The words are the standard's, not a language's: `LTE`, `4G` and `Wi-Fi` are written the
# same in a Latvian, a Polish and a Finnish feed. `no 4G` is a tablet saying what it lacks.
# `Cell` is rdveikals' short form, `WiFi+Cell`, on 9 of its 584 tablets.
_CELLULAR = re.compile(r"(?<!no )(?<!bez )\b(?:LTE|4G|5G|Cell(?:ular)?)\b", re.IGNORECASE)
# Any hyphen: 1a and ksenukai write `Wi‑Fi` with a non-breaking one, U+2011, and the plain
# `-` alone found 148 of their 229 tablets' connectivity where the titles stated it on more.
# The standard a field is named after, `4G savienojums`.
_STANDARD = re.compile(r"\b[345]G\b", re.IGNORECASE)
_WIFI = re.compile(r"\bWi[-\u2010\u2011]?Fi\b", re.IGNORECASE)
# The same words, as a model carries them. On a tablet they name the version, not the model:
# `Galaxy Tab S10 FE 5G` is the cellular `Galaxy Tab S10 FE`. On a phone they do not, which
# is why this is a tablet's rule — `Galaxy A16` and `Galaxy A16 5G` are two phones.
_CONNECTIVITY_WORD = re.compile(
    r"\s*\b(?:Wi[-\u2010\u2011]?Fi|LTE|4G|5G|Cell(?:ular)?)\b", re.IGNORECASE
)
# What is left between two of them: `Wi-Fi + Cellular` loses both words and keeps its `+`.
_DANGLING = re.compile(r"(?:^|\s)[+&/](?=\s|$)")

# A screen size as a shop writes it: `11"`, `11''`, `11”`, `11-inch`, `11 inches`, `11 in`,
# and the metric `27,59cm (11")`, where the inches in the bracket are the maker's own figure.
_INCHES = re.compile(
    r"(?<![\d.,])(\d{1,2}(?:[.,]\d{1,2})?)\s*(?:\"|''|”|″|-?\s?inch(?:es)?\b|\s?in\b)",
    re.IGNORECASE,
)
_CENTIMETRES = re.compile(r"(?<![\d.,])(\d{2}(?:[.,]\d{1,2})?)\s?cm\b", re.IGNORECASE)
# Anything size-like on the model itself, to be taken off before the canonical size goes on.
_SIZE_ON_MODEL = re.compile(
    r"(?:\(\s*)?(?<![\d.,])\d{1,2}(?:[.,]\d{1,2})?\s*(?:\"|''|”|″|-?\s?inch(?:es)?\b|\s?in\b|\s?cm\b)(?:\s*\))?",
    re.IGNORECASE,
)
_BARE_NUMBER = re.compile(r"\d{1,2}(?:[.,]\d{1,2})?")
# A maker names a tablet by its screen in whole inches — `iPad Air 11`, `iPad Pro 13` — and
# a shop writes the same screen as `10.9"`, `11"` or `27,59cm`. Within one line the sizes a
# maker sells differ by an inch or more, so rounding cannot fold two of them into one.
_SMALLEST_TABLET, _LARGEST_TABLET = 7, 15


def _connectivity(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    title = str(fields.get("title") or "")
    said = {
        found for found in (_said_in_title(title), _said_in_a_field(fields, vocabulary)) if found
    }
    # Two sources naming different radios: neither is taken, as with storage.
    if len(said) != 1:
        return {}
    return {"identity": {**fields.get("identity", {}), CONNECTIVITY_KEY: said.pop()}}


def _said_in_title(title: str) -> str | None:
    if _CELLULAR.search(title):
        return "cellular"
    if _WIFI.search(title):
        return "wifi"
    return None


def _said_in_a_field(fields: dict[str, Any], vocabulary: Vocabulary) -> str | None:
    """What the shop's fields for connectivity say, read through the registry.

    Four shops answer the question in fields: rdveikals names the standard, `5G`; the rest
    answer yes or no — ksenukai's and 1a's `4G savienojums: Nē`, bigbox's `Mobilie sakari:
    Ir`, dateks' `4G: Nav`. A standard is a cellular tablet in any language; a yes or a no is
    a word, and the registry says what it means. A tablet answering for several standards is
    cellular if any answer is yes — `3G: Nē` beside `4G: Jā` is a 4G tablet. A word the
    registry does not know says nothing: reading every answer that is not a standard as
    `none` once read `Jā` as a Wi-Fi tablet.
    """
    said: set[str] = set()
    denied: set[str] = set()
    for name, value in (fields.get("attributes") or {}).items():
        if vocabulary.attribute_key(str(name)) != CONNECTIVITY_KEY:
            continue
        text = str(value or "").strip()
        if not text:
            continue
        meant = (
            "cellular" if _CELLULAR.search(text) else vocabulary.value_of(CONNECTIVITY_KEY, text)
        )
        standard = _STANDARD.search(str(name))
        if meant == "wifi" and standard:
            # `4G savienojums: Nē` denies 4G, not a modem: ksenukai's index answers for 3G
            # and 4G and never for 5G, and nine of its 5G tablets read as Wi-Fi from it.
            denied.add(standard.group().upper())
        elif meant:
            said.add(meant)
    if "cellular" in said:
        return "cellular"
    # A denial of every standard up to the newest is a denial of the modem.
    if "wifi" in said or "5G" in denied:
        return "wifi"
    return None


def _model_without_connectivity(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    model = (fields.get("model") or "").strip()
    if not model:
        return {}
    shorter = " ".join(_DANGLING.sub(" ", _CONNECTIVITY_WORD.sub(" ", model)).split())
    return {"model": shorter} if shorter and shorter != model else {}


# A shop's quotes and table rules at either end of a name: `"Acer Iconia A10`, `| Iconia V11`.
_EDGE_MARKS = re.compile(r"^[\s\"'„“”|/,.:;-]+|[\s\"'„“”|/,.:;-]+$")


def _model_bare(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    model = fields.get("model") or ""
    bare = _EDGE_MARKS.sub("", model)
    return {"model": bare} if bare and bare != model else {}


def _model_names_the_maker_once(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    model = fields.get("model") or ""
    maker = (fields.get("brand_raw") or "").strip().casefold()
    if not model or not maker:
        return {}
    words = [word for word in model.split() if word.casefold() != maker]
    shorter = " ".join(words)
    return {"model": shorter} if shorter and shorter != model else {}


def _screen_inches(title: str) -> int | None:
    """The screen a title states, in whole inches, or nothing."""
    found = _INCHES.search(title)
    if found:
        inches = float(found.group(1).replace(",", "."))
    else:
        metric = _CENTIMETRES.search(title)
        if metric is None:
            return None
        inches = float(metric.group(1).replace(",", ".")) / 2.54
    rounded = int(inches + 0.5)
    return rounded if _SMALLEST_TABLET <= rounded <= _LARGEST_TABLET else None


def _stated_inches(fields: dict[str, Any], vocabulary: Vocabulary) -> int | None:
    """The screen a shop's own field gives, when its title gives none.

    bigbox writes `iPad Mini (A17 Pro)` in the name and `8.3` in `Ekrāna diagonāle`, and 1a
    writes `8.3"` in the name: without the field the two read as two models.
    """
    for name, value in (fields.get("attributes") or {}).items():
        if vocabulary.attribute_key(str(name)) != SCREEN_KEY:
            continue
        # Inches first where the value states them beside centimetres: dateks and
        # rdveikals write `27,9 cm (11")`, and the first number there is not the screen.
        stated = _screen_inches(str(value))
        if stated is not None:
            return stated
        found = re.search(r"\d{1,2}(?:[.,]\d{1,2})?", str(value))
        if found:
            rounded = int(float(found.group().replace(",", ".")) + 0.5)
            if _SMALLEST_TABLET <= rounded <= _LARGEST_TABLET:
                return rounded
    return None


def _size_is_an_axis(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The screen off the model, wherever the shop wrote it, and onto the identity."""
    model = (fields.get("model") or "").strip()
    inches = _screen_inches(str(fields.get("title") or "")) or _stated_inches(fields, vocabulary)
    found: dict[str, Any] = {}
    if model:
        bare = " ".join(_SIZE_ON_MODEL.sub(" ", model).split())
        # The size with no unit: where the name runs straight on into the configuration,
        # rdveikals' `Galaxy Tab A11 8.7 8GB`, and where an earlier rule took the inch mark
        # off the end, its `Redmi Pad 2 11"`. Only a number that rounds to the screen stated
        # — `Redmi Pad 2` at 11" keeps its 2. A maker's `MatePad 11` at 11" loses its 11 at
        # every shop alike, and the axis still keeps it apart from the 12" `MatePad`.
        last = bare.rsplit(" ", 1)
        if (
            inches is not None
            and len(last) == 2
            and _BARE_NUMBER.fullmatch(last[1])
            and int(float(last[1].replace(",", ".")) + 0.5) == inches
        ):
            bare = last[0]
        if bare and bare != model:
            found["model"] = bare
    if inches is not None:
        found["identity"] = {**fields.get("identity", {}), SCREEN_KEY: inches}
    return found


RULESET = register(
    CATEGORY,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="tablets-storage",
                layer=CATEGORY,
                why=(
                    "The phone rule, unchanged: over 1089 of m79's tablets it read a"
                    " capacity on 956, and a tablet's storage tells two of one model apart"
                    " exactly as a phone's does."
                ),
                body=devices.storage,
            ),
            Rule(
                id="tablets-color",
                layer=CATEGORY,
                why="A shop's colour field, resolved through the registry, as for a phone.",
                body=devices.color,
            ),
            Rule(
                id="tablets-color-from-title",
                layer=CATEGORY,
                why=(
                    "A colour the registry knows, whole in the title, when no field gave"
                    " one: 741 of 1089 at m79 between the two colour rules."
                ),
                body=devices.color_from_title,
            ),
            Rule(
                id="tablets-connectivity",
                layer=CATEGORY,
                why=(
                    "Wi-Fi or cellular, from the name, because that is where every shop puts"
                    " it: of m79's 1089, 323 name a cellular standard and 373 only Wi-Fi."
                    " A tablet with both words is the cellular one — every cellular tablet"
                    " also has Wi-Fi. The other 393 say neither, and most of those are"
                    " models with no cellular version at all; reading them as Wi-Fi would"
                    " be right more often than not and would still be a guess, so they are"
                    " left without the axis. A field the registry knows as connectivity"
                    " is read too, and a title and a field naming different radios leave"
                    " the axis empty rather than pick one."
                ),
                body=_connectivity,
            ),
            Rule(
                id="tablets-model-bare-of-marks",
                layer=FINISH,
                why=(
                    '`"Acer Iconia A10` and `| Iconia V11-21M`: a quote a shop opened and a'
                    " table rule it wrote its title in, left at the edge of the model by the"
                    " cut. First of the model rules, because the maker comes off only a model"
                    " that begins with the maker's name."
                ),
                body=_model_bare,
            ),
            Rule(
                id="tablets-model-does-not-repeat-the-maker",
                layer=FINISH,
                why="As for a phone: the title composes brand and model, so a model holds none.",
                body=devices.without_the_maker,
            ),
            Rule(
                id="tablets-model-from-the-registry",
                layer=FINISH,
                why="As for a phone: the registry's spelling of a name found whole in the title.",
                body=devices.from_the_registry,
            ),
            Rule(
                id="tablets-model-names-the-maker-once",
                layer=FINISH,
                why=(
                    '`iPad Air 13" Apple M3`: Apple names its chips `Apple M3`, and the maker'
                    " is then left in the middle of the model, where the rule that takes it"
                    " off the front never looks. bigbox writes it and m79 does not, so the"
                    " same tablet read two ways."
                ),
                body=_model_names_the_maker_once,
            ),
            Rule(
                id="tablets-model-without-a-trailing-colour",
                layer=FINISH,
                why="As for a phone: a colour the registry knows comes off the end.",
                body=devices.without_a_trailing_colour,
            ),
            Rule(
                id="tablets-model-without-connectivity",
                layer=FINISH,
                why=(
                    "`Galaxy Tab S10 FE 5G` is the cellular `Galaxy Tab S10 FE`, and"
                    " `Galaxy Tab A11 Wi-Fi` the other one: on a tablet the word names the"
                    " version, which the connectivity axis already carries. Left on the"
                    " model it would make the Wi-Fi and the cellular tablet two models."
                ),
                body=_model_without_connectivity,
            ),
            Rule(
                id="tablets-size-is-an-axis",
                layer=FINISH,
                why=(
                    '`iPad Air 11"` and `iPad Air 13"` are two tablets at two prices: 83 pairs'
                    " of different barcodes over bigbox's 580 tablets on 23.09.2026 that"
                    " storage, colour and connectivity could not tell apart differed in the"
                    " screen. So the screen tells a tablet apart, and it is an axis, like"
                    " storage — not part of the name, where it had been at first and where"
                    " the storefront read `Galaxy Tab A11+ 11`. A shop writes one screen as"
                    ' `11"`, `11-inch`, `27,59cm (11")` or `10.9"`, and a maker names it in'
                    " whole inches, so it is taken off the model wherever it stands and"
                    " kept rounded: within one line the sizes a maker sells differ by an"
                    " inch or more, and rounding cannot fold two of them into one. Last of"
                    " all, after a colour has come off the end."
                ),
                body=_size_is_an_axis,
            ),
        ),
    ),
)
