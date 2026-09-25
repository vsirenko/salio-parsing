"""Reading bm.market's laptops.

Apart from `bm.py` because the rules import the laptop category, and a ruleset's fingerprint
covers what its module imports. bm's attributes are its own codes — `bm_procesora_serija_165`
— and the chip is split over three of them.
"""

from typing import Any

from app.features.offers.normalization.categories import laptops
from app.features.offers.normalization.rules import SOURCE, Rule, Ruleset, Vocabulary, register

LAPTOPS_SLUG = "bm-laptops"
LAPTOPS_VERSION = "bm-laptops-5"
CPU_FIELDS = (
    "bm_procesora_razotajs_213",
    "bm_procesora_serija_165",
    "bm_procesora_modelis_2400",
)


def _cpu_from_its_fields(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    attributes = payload.get("attributes") or {}
    return laptops.chip_from_fields(
        [str(attributes.get(name) or "") for name in CPU_FIELDS], fields
    )


LAPTOPS_RULESET = register(
    SOURCE,
    LAPTOPS_SLUG,
    Ruleset(
        version=LAPTOPS_VERSION,
        rules=(
            Rule(
                id="bm-laptops-cpu-from-its-fields",
                layer=SOURCE,
                why=(
                    "Maker, series and model in three of the shop's coded fields — `AMD`,"
                    " `AMD Ryzen 7`, `7435HS` — the model on 140 of 396 laptops on 24.09.2026."
                    " Joined, they are the chip, checked against the title."
                ),
                body=_cpu_from_its_fields,
            ),
        ),
    ),
)
