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
VERSION = "tablets-2"

CONNECTIVITY_KEY = "connectivity"
# The words are the standard's, not a language's: `LTE`, `4G` and `Wi-Fi` are written the
# same in a Latvian, a Polish and a Finnish feed. `no 4G` is a tablet saying what it lacks.
_CELLULAR = re.compile(r"(?<!no )(?<!bez )\b(?:LTE|4G|5G|Cellular)\b", re.IGNORECASE)
_WIFI = re.compile(r"\bWi-?Fi\b", re.IGNORECASE)
# The same words, as a model carries them. On a tablet they name the version, not the model:
# `Galaxy Tab S10 FE 5G` is the cellular `Galaxy Tab S10 FE`. On a phone they do not, which
# is why this is a tablet's rule — `Galaxy A16` and `Galaxy A16 5G` are two phones.
_CONNECTIVITY_WORD = re.compile(r"\s*\b(?:Wi-?Fi|LTE|4G|5G|Cellular)\b", re.IGNORECASE)
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
# A maker names a tablet by its screen in whole inches — `iPad Air 11`, `iPad Pro 13` — and
# a shop writes the same screen as `10.9"`, `11"` or `27,59cm`. Within one line the sizes a
# maker sells differ by an inch or more, so rounding cannot fold two of them into one.
_SMALLEST_TABLET, _LARGEST_TABLET = 7, 15


def _connectivity(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    title = str(fields.get("title") or "")
    if _CELLULAR.search(title):
        found = "cellular"
    elif _WIFI.search(title):
        found = "wifi"
    else:
        return {}
    return {"identity": {**fields.get("identity", {}), CONNECTIVITY_KEY: found}}


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


def _model_with_its_size(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    model = (fields.get("model") or "").strip()
    inches = _screen_inches(str(fields.get("title") or ""))
    if not model or inches is None:
        return {}
    bare = " ".join(_SIZE_ON_MODEL.sub(" ", model).split())
    if not bare:
        return {}
    # Already named by it — `iPad Pro 13`, a registry name carrying its size.
    canonical = bare if bare.split()[-1] == str(inches) else f"{bare} {inches}"
    return {"model": canonical} if canonical != model else {}


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
                    " left without the axis."
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
                id="tablets-size-ends-the-model",
                layer=FINISH,
                why=(
                    '`iPad Air 11"` and `iPad Air 13"` are two tablets at two prices, and'
                    " bigbox's name rule cut both to `iPad Air`: 83 pairs of different"
                    " barcodes over 580 of its tablets on 23.09.2026 that storage, colour and"
                    " connectivity could not tell apart differed in the screen. A maker"
                    " names a tablet by its screen in whole inches, so the size a title"
                    ' states — `11"`, `11-inch`, `27,59cm (11")`, `10.9"` — is taken off'
                    " the model wherever it stands and put back at the end, rounded:"
                    ' `11-inch iPad Air` and `iPad Air 10.9"` both read `iPad Air 11`. A'
                    " title stating no size leaves the model without one, which can split"
                    " one tablet in two but never fold two into one."
                ),
                body=_model_with_its_size,
            ),
        ),
    ),
)
