"""Reading what discover.lv's export hands over.

Written against 560 real phones collected on 22.09.2026. The export states a name, a price,
a section and a flag, and generic finds the first two. Everything else this shop knows is
inside the name, which is the tidiest here: `BRAND MODEL CAPACITY COLOUR`, with the maker's
designation for the family in brackets when there is one.

There is no barcode on this shop at all — not in the export and not on the page — so what
this module reads is what the matcher has to work with.
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

SLUG = "discover-phones"
VERSION = "discover-5"

# `256GB`, `1 TB`. The one boundary in a name that has no separators.
SIZE = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:TB|GB|MB)\b", re.IGNORECASE)
# `12/128GB` writes the working memory and the capacity as one, and only the second half
# carries a unit — so cutting at the unit leaves `12/` behind, on the model.
_RAM_PREFIX = re.compile(r"\s*\d+\s*/\s*$")
_EDGES = re.compile(r"^[\s,/|-]+|[\s,/|-]+$")


def _model(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The model, cut out of the name in front of the first capacity."""
    name = (payload.get("name") or "").strip()
    if not name:
        return {}

    head = _without_family(name, payload.get("line") or "")
    head = naming.without_brand(head, payload.get("brand") or "")
    found = SIZE.search(head)
    if found:
        head = _RAM_PREFIX.sub("", head[: found.start()])

    model = _EDGES.sub("", " ".join(head.split()))
    return {"model": model[:200]} if model else {}


def _without_family(name: str, line: str) -> str:
    """The name with `(SM-S948B)` taken out, and every other bracket left where it is.

    Taking out any bracket is what this did first, and it cost `Apple iPhone SE (2022)` its
    year — which is not decoration on an iPhone SE, it is which one. Only the string the
    channel read as the family comes out.
    """
    return name.replace(f"({line})", " ") if line else name


def _line(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    line = (payload.get("line") or "").strip()
    return {"_line": line} if line else {}


def _color(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """Colour out of what follows the last capacity in the name."""
    if not vocabulary.colours or (fields.get("identity") or {}).get("color"):
        return {}

    name = (payload.get("name") or "").strip()
    last = None
    for found in SIZE.finditer(name):
        last = found
    if last is None:
        return {}

    tail = _EDGES.sub(
        "", " ".join(_without_family(name[last.end() :], payload.get("line") or "").split())
    )
    canonical = colours.resolve(tail, vocabulary) if tail else None
    return {"identity": {**fields.get("identity", {}), "color": canonical}} if canonical else {}


RULESET = register(
    SOURCE,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="discover-model",
                layer=SOURCE,
                why=(
                    "The export states no model, so all 560 read without one. The name is"
                    " the tidiest of the ten shops here — `BRAND MODEL CAPACITY COLOUR`,"
                    " with no marketing sentence around it — so the brand comes off the"
                    " front and the first capacity is the cut. 560 of 560 yield one."
                    "\n\n"
                    "Two things it got wrong at first, and both split one phone into"
                    " several. **217 of the 560 write the configuration as `12/128GB`**,"
                    " working memory and capacity as one with a unit only on the second"
                    " half, so cutting at the unit left `12/` behind and `Pixel 10` became"
                    " `Pixel 10 12`, `Pixel 10 16` and so on — one entry per memory size."
                    " And **taking out any bracket, to be rid of `(SM-S948B)`, cost"
                    " `Apple iPhone SE (2022)` its year**, which on an iPhone SE is not"
                    " decoration but which one it is. Only the string the channel read as"
                    " the family comes out now. Distinct models: 135 before, 117 after."
                ),
                body=_model,
            ),
            Rule(
                id="discover-line",
                layer=SOURCE,
                why=(
                    "`(SM-S948B)` is on 222 of the 560 and it is not a part number: the same"
                    " string covers every colour and capacity of that phone. Offered as an"
                    " `mpn` it would send the part-number rung looking for one product and"
                    " finding nine, which is the mistake rdveikals' `Viedtālruņa modelis`"
                    " and bigbox's `Tālruņa modelis` were both caught making. It is a"
                    " product line, so it goes where the layer below the brand selects on."
                ),
                body=_line,
            ),
            Rule(
                id="discover-colour",
                layer=SOURCE,
                why=(
                    "The only place this shop states a colour is the end of the name, after"
                    " the capacity, and there is no specification table to fall back on"
                    " because the product page is not opened. Measured: 517 of 560 (92.3%)"
                    " resolve through the registry. The rest is the maker's marketing —"
                    " `Fog`, `Midnight`, `Canyon`, `Blueberry` — left unresolved on purpose,"
                    " which matters more here than elsewhere: with no barcode anywhere on"
                    " this shop, colour is one of the two axes its listings are told apart"
                    " by, and a wrong one would not be caught by a stronger signal."
                ),
                body=_color,
            ),
        ),
    ),
)


# The tablets come out of the same export, in two sections that name no maker —
# `Datortehnika >> Portatīvie/Planšetdatori` — and in names that state the screen as a bare
# number: `Samsung Galaxy Tab S10 FE WiFi 10.9 128GB Gray (SM-X520)`, `Apple iPad Air 11 M3
# (2025) 128GB`. Measured on 222 collected on 23.09.2026.
TABLETS_SLUG = "discover-tablets"
TABLETS_VERSION = "discover-tablets-2"

# `X230`, `T636`: Samsung's short model code, which this shop puts between the maker and
# `Galaxy` — `Samsung X230 Galaxy Tab A11+`.
_LEADING_CODE = re.compile(r"^[A-Z]\d{3}[A-Z]?\s+(?=Galaxy\b)")
_BARE_SIZE = re.compile(r"^\d{1,2}(?:[.,]\d{1,2})?\"?$")
_SMALLEST, _LARGEST = 7, 15


def _maker_from_name(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The first word of the name that is a maker the catalogue knows, where the section
    named none. The words for the category come first on some: `Planšetdators Apple …`."""
    if fields.get("brand_raw"):
        return {}
    for word in str(payload.get("name") or "").split():
        folded = word.casefold()
        if folded in vocabulary.category_names:
            continue
        return {"brand_raw": word} if folded in vocabulary.brand_names else {}
    return {}


def _screen_token(head: str) -> str | None:
    """The last bare number in the name's head that is a tablet's screen."""
    found = None
    for word in head.split():
        if _BARE_SIZE.match(word):
            size = float(word.rstrip('"').replace(",", "."))
            if _SMALLEST <= size < _LARGEST + 0.5:
                found = word
    return found


def _tablet_model(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The phones' cut, less the maker's short code and the screen standing in the name."""
    name = (payload.get("name") or "").strip()
    head = _without_family(name, payload.get("line") or "")
    found = SIZE.search(head)
    if found:
        head = head[: found.start()]
    screen = _screen_token(head)
    words = head.split()
    maker = str(fields.get("brand_raw") or payload.get("brand") or "").casefold()
    while words and (
        words[0].casefold() in vocabulary.category_names or words[0].casefold() == maker
    ):
        words = words[1:]
    if screen and screen in words:
        # The last one: `Xiaomi Pad 8 11` is the Pad 8 with an 11-inch screen.
        at = len(words) - 1 - words[::-1].index(screen)
        words = words[:at] + words[at + 1 :]
    model = _LEADING_CODE.sub("", _EDGES.sub("", _RAM_PREFIX.sub("", " ".join(words))))
    found_screen = {}
    if screen:
        inches = int(float(screen.rstrip('"').replace(",", ".")) + 0.5)
        found_screen = {"identity": {**fields.get("identity", {}), "screen_inch": inches}}
    return {"model": model[:200], **found_screen} if model else found_screen


_RADIO = re.compile(r"\b(?:Wi-?Fi|Cell(?:ular)?|LTE|[345]G)\b", re.IGNORECASE)


def _an_ipad_naming_no_radio(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """Wi-Fi, for an iPad whose name states no radio at all."""
    identity = fields.get("identity") or {}
    name = str(payload.get("name") or "")
    if identity.get("connectivity") or not re.search(r"\biPad\b", name, re.IGNORECASE):
        return {}
    if _RADIO.search(name):
        return {}
    return {"identity": {**identity, "connectivity": "wifi"}}


TABLETS_RULESET = register(
    SOURCE,
    TABLETS_SLUG,
    Ruleset(
        version=TABLETS_VERSION,
        rules=(
            Rule(
                id="discover-tablets-maker-from-name",
                layer=SOURCE,
                why=(
                    "The phones' section names the maker, `Mobilie telefoni >> Samsung`; the"
                    " tablets' names a kind of thing, `Portatīvie/Planšetdatori`, so 122 of"
                    " 222 tablets came with no brand. The name begins with the maker on all"
                    " of them, after the word for the category where there is one."
                ),
                body=_maker_from_name,
            ),
            Rule(
                id="discover-tablets-model",
                layer=SOURCE,
                why=(
                    "The phones' cut at the first capacity read a model for 15 of 222: the"
                    " maker stayed on the front where the section gave none. The screen is"
                    " a bare number in the name — `Tab S10 FE WiFi 10.9 128GB`, `iPad Air 11"
                    " M3` — on 195 of 222, and every lone one in 7-15 inches before the"
                    " capacity was the screen; where there are two, `Xiaomi Pad 8 11`, the"
                    " first is the model's and the last the screen. It goes to the axis and"
                    " out of the model, and so does Samsung's short code before `Galaxy`."
                ),
                body=_tablet_model,
            ),
            Rule(
                id="discover-tablets-line",
                layer=SOURCE,
                why="The code in brackets is a family here as it is for the phones.",
                body=_line,
            ),
            Rule(
                id="discover-tablets-an-ipad-naming-no-radio-is-wifi",
                layer=SOURCE,
                why=(
                    "This shop names a cellular iPad `… + Cellular …` and a Wi-Fi one with no"
                    " radio at all: `Apple iPad Air 11 M4 (2026) 128GB Blue (MH314)`. Checked"
                    " by the part number in brackets on 23.09.2026: of the 27 such iPads"
                    " another shop also lists, all 27 are Wi-Fi there, and none is cellular."
                    " Only iPads: no other maker's unworded tablets could be checked, and"
                    " they are left without the axis."
                ),
                body=_an_ipad_naming_no_radio,
            ),
            Rule(
                id="discover-tablets-colour",
                layer=SOURCE,
                why="The name ends in the colour after the capacity, as for the phones.",
                body=_color,
            ),
        ),
    ),
)
