"""Reading euronics.lv's laptops.

Apart from `euronics.py` because the rules import the laptop category, and a ruleset's
fingerprint covers what its module imports. The specification table carries the rest; what
is this shop's is the chip, over three fields — `processor producer: Intel`, `processor
type: Core Ultra 7`, `processor: 255H` — of which the last is a core count on its MacBooks
(`10-core`), which names nothing and is harmless beside `Apple M5`.
"""

from typing import Any

from app.features.offers.normalization.categories import laptops
from app.features.offers.normalization.rules import SOURCE, Rule, Ruleset, Vocabulary, register

LAPTOPS_SLUG = "euronics-laptops"
LAPTOPS_VERSION = "euronics-laptops-4"
CPU_FIELDS = ("processor producer", "processor type", "processor")


def _cpu_from_its_fields(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    specs = payload.get("specs") or {}
    return laptops.chip_from_fields([str(specs.get(name) or "") for name in CPU_FIELDS], fields)


LAPTOPS_RULESET = register(
    SOURCE,
    LAPTOPS_SLUG,
    Ruleset(
        version=LAPTOPS_VERSION,
        rules=(
            Rule(
                id="euronics-laptops-cpu-from-its-fields",
                layer=SOURCE,
                why=(
                    "The shop states the chip over three fields, each naming nothing alone —"
                    " `Intel`, `Core i5`, `12450` — on all 258 laptops of 24.09.2026, and the"
                    " titles give only the family: `…, 16'', WUXGA, i5, 16 GB, …`. Joined, the"
                    " fields are the chip, checked against the title."
                ),
                body=_cpu_from_its_fields,
            ),
        ),
    ),
)
