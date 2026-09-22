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
VERSION = "discover-2"

# `256GB`, `1 TB`. The one boundary in a name that has no separators.
SIZE = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:TB|GB|MB)\b", re.IGNORECASE)
# `12/128GB` writes the working memory and the capacity as one, and only the second half
# carries a unit — so cutting at the unit leaves `12/` behind, on the model.
_RAM_PREFIX = re.compile(r"\s*\d+\s*/\s*$")
_EDGES = re.compile(r"^[\s,/|-]+|[\s,/|-]+$")


def _availability(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    return {"availability": "in_stock"} if str(payload.get("in_stock") or "").strip() == "1" else {}


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
                id="discover-availability",
                layer=SOURCE,
                why=(
                    "`in_stock` is `1` on all 560, so as a field it says nothing — and as a"
                    " fact it says everything: the export holds what the shop is willing to"
                    " sell, and a product that leaves it has left the shop. Read here rather"
                    " than left to generic, whose table knows `true` and `yes` and not `1`,"
                    " so all 560 were arriving `unknown` on a channel that declares it"
                    " delivers availability. What this shop cannot say is the difference"
                    " between stock and to-order; it does not distinguish them either."
                ),
                body=_availability,
            ),
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
