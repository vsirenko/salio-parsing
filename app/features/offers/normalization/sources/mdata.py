"""Reading what mdata.lv's pages hand over.

Written against 98 new phones collected on 22.09.2026 — the shop's whole catalogue once the
refurbished 71% is left at the channel. Generic already finds the title, the maker, the
price, the part number and, through the category's rules, the colour on 91% and the
capacity on 99%, because this shop states each of them as a field rather than burying them
in a sentence. Three things are left.
"""

import re
from typing import Any

from app.features.offers.normalization import naming
from app.features.offers.normalization.rules import (
    SOURCE,
    Rule,
    Ruleset,
    Vocabulary,
    register,
)

SLUG = "mdata-phones"
VERSION = "mdata-3"


# `128GB`, `4/ 64GB`, `6/ 256GB` — the configuration, written with the working memory in
# front of the capacity as often as not, and with the shop's own stray space after a slash.
SIZE = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:TB|GB|MB)\b", re.IGNORECASE)
# The second number has to look like a capacity — two digits at least. `ARMOR MINI 20/ 6/
# 256GB` otherwise cuts at `20/ 6`, which is the model number meeting the memory, and the
# model becomes `ARMOR MINI` with the 20 thrown away.
SLASH = re.compile(r"\b\d{1,3}\s*/\s*\d{2,4}(?:\s?(?:TB|GB|MB))?\b", re.IGNORECASE)
_EDGES = re.compile(r"^[\s,./|-]+|[\s,./|-]+$")


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
