"""Reading what euronics.lv's tablet pages hand over.

The phones need no rule of this channel's own: the page's JSON-LD states the model outright,
and generic reads it. The tablets carry the same field, and on 122 collected on 23.09.2026 it
is right for Apple — `iPad Pro 11" M5`, `iPad Air M4 13`, the chip that the name leaves after
a comma — and short for Samsung, where the shop drops the series: `Tab S11 Ultra` for a name
that reads `Samsung Galaxy Tab S11 Ultra, 256 GB, 5G, gray - Tablet`.
"""

from typing import Any

from app.features.offers.normalization import naming
from app.features.offers.normalization.rules import SOURCE, Rule, Ruleset, Vocabulary, register

TABLETS_SLUG = "euronics-tablets"
TABLETS_VERSION = "euronics-tablets-1"


def _model_with_its_series(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The name's head, where it is the stated model with the series in front of it."""
    model = str(fields.get("model") or "").strip()
    name = str(payload.get("name") or "").strip()
    if not model or not name:
        return {}
    head = naming.without_brand(name.split(",")[0].strip(), payload.get("brand") or "")
    if head != model and head.casefold().endswith(" " + model.casefold()):
        return {"model": head[:200]}
    return {}


TABLETS_RULESET = register(
    SOURCE,
    TABLETS_SLUG,
    Ruleset(
        version=TABLETS_VERSION,
        rules=(
            Rule(
                id="euronics-tablets-model-with-its-series",
                layer=SOURCE,
                why=(
                    "The shop's stated model is `Tab S11`, `Tab S10 Lite`, `Tab S11 Ultra` for"
                    " five Samsung tablets whose names say `Galaxy Tab …`, and every other"
                    " shop writes the series. Where the name before its first comma ends with"
                    " the stated model, the name is the model with the part the shop left"
                    ' off; where it does not — `iPad Pro 11"` against `iPad Pro 11" M5` —'
                    " the stated model stands, because the name has lost the chip."
                ),
                body=_model_with_its_series,
            ),
        ),
    ),
)
