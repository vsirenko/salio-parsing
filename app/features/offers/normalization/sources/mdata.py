"""Reading what mdata.lv's pages hand over.

Written against 98 new phones collected on 22.09.2026 — the shop's whole catalogue once the
refurbished 71% is left at the channel. Generic already finds the title, the maker, the
price, the part number and, through the category's rules, the colour on 91% and the
capacity on 99%, because this shop states each of them as a field rather than burying them
in a sentence. Three things are left.
"""

import re
from typing import Any

from app.features.offers.normalization import barcodes, naming
from app.features.offers.normalization.rules import (
    SOURCE,
    Rule,
    Ruleset,
    Vocabulary,
    register,
)

SLUG = "mdata-phones"
VERSION = "mdata-1"

# What this shop says instead of whether it has the thing. Both mean it can be bought.
SHIPS_IN = ("VEIKALĀ", "1-2 days", "3-5 days")

# `128GB`, `4/ 64GB`, `6/ 256GB` — the configuration, written with the working memory in
# front of the capacity as often as not, and with the shop's own stray space after a slash.
SIZE = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:TB|GB|MB)\b", re.IGNORECASE)
# The second number has to look like a capacity — two digits at least. `ARMOR MINI 20/ 6/
# 256GB` otherwise cuts at `20/ 6`, which is the model number meeting the memory, and the
# model becomes `ARMOR MINI` with the 20 thrown away.
SLASH = re.compile(r"\b\d{1,3}\s*/\s*\d{2,4}(?:\s?(?:TB|GB|MB))?\b", re.IGNORECASE)
_EDGES = re.compile(r"^[\s,./|-]+|[\s,./|-]+$")


def _barcode(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    return {"gtin": barcodes.pick(payload.get("barcodes"))}


def _availability(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    flag = str(payload.get("availability") or "").strip()
    return {"availability": "in_stock"} if flag in SHIPS_IN else {}


def _model(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The model the shop states, and only where it does not state one, the title."""
    stated = str((payload.get("specs") or {}).get("Model") or "").strip()
    if stated:
        return {"model": stated[:200]}

    title = str(fields.get("title") or payload.get("name") or "")
    if not title:
        return {}
    head = naming.without_brand(title, payload.get("brand") or "")
    found = [match for match in (SIZE.search(head), SLASH.search(head)) if match]
    if found:
        head = head[: min(found, key=lambda match: match.start()).start()]
    model = _EDGES.sub("", head).strip()
    return {"model": model[:200]} if model else {}


RULESET = register(
    SOURCE,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="mdata-barcode",
                layer=SOURCE,
                why=(
                    "The shop has two of its own `schema.org` fields the wrong way round:"
                    " `model` holds the barcode and `mpn` an internal number, and the"
                    " maker's part number is in the prose of `description` behind"
                    " `Manufacturer code:`. So nothing is trusted by the name of the field"
                    " it came in: the channel hands the numbers over as a list and"
                    " `barcodes.pick` chooses, as it does for every shop. All 98 carry at"
                    " least one candidate and the check digit sorts them."
                ),
                body=_barcode,
            ),
            Rule(
                id="mdata-availability",
                layer=SOURCE,
                why=(
                    "This shop says how soon rather than whether: `1-2 days` on 90 of the 98"
                    " and `3-5 days` on the other 8, with `VEIKALĀ` for what is on a shelf."
                    " All three mean it can be bought. There is no out-of-stock word here"
                    " because the shop does not list what it has not got — and if one ever"
                    " appears it will read as `unknown` and be visible, which is the right"
                    " way round. Not from the page's own JSON-LD, which reads `InStock` for"
                    " everything: the fifth shop in a row whose structured data means it"
                    " will sell the thing rather than that it has it."
                ),
                body=_availability,
            ),
            Rule(
                id="mdata-model",
                layer=SOURCE,
                why=(
                    "The shop states the model as a field — `Model iPhone 15`, `Model Galaxy"
                    " A26` — on 65 of the 98, which is better than any cut of a title can"
                    " be and is taken as it stands. The other 33 are records the shop has"
                    " not described, where the whole of the description is the barcode, the"
                    " part number and the warranty; for those the name is cut the ordinary"
                    " way, at the configuration. This shop writes it both as `128GB` and as"
                    " `6/ 256GB` — memory first, capacity second, with a stray space after"
                    " the slash — so the earliest of the two matches is the cut. The second"
                    " half of a pair has to look like a capacity for the pair to count:"
                    " `ARMOR MINI 20/ 6/ 256GB` otherwise cuts at `20/ 6`, which is the"
                    " model number meeting the memory, and the 20 is thrown away."
                ),
                body=_model,
            ),
        ),
    ),
)
