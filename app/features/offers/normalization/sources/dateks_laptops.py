"""Reading dateks.lv's laptops.

Apart from `dateks.py` because the rules import the laptop category, and a ruleset's
fingerprint covers what its module imports.

dateks lists a laptop's drives under `SSD` and `HDD`, and it also fills a field its phones
use for their storage, `Atmiņa > Iekšējā atmiņa`, which on a laptop holds the working memory:
on 24.09.2026 it was there on 234 of 747 and equal to `Operatīvā atmiņa` on 220. The
registry maps that name to storage, rightly for a phone, so the category's rule saw 16 GB and
512 GB for one drive and took neither — 361 laptops without storage.
"""

import re
from typing import Any

from app.features.offers.normalization.categories import laptops
from app.features.offers.normalization.rules import SOURCE, Rule, Ruleset, Vocabulary, register

LAPTOPS_SLUG = "dateks-laptops"
LAPTOPS_VERSION = "dateks-laptops-5"
DRIVE_FIELDS = ("SSD", "HDD")
_SIZE = re.compile(r"(\d{1,4}(?:[.,]\d)?)\s?(TB|GB)\b", re.IGNORECASE)


def _storage_from_its_drives(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The one drive `SSD` or `HDD` states, where the title does not name another."""
    parameters = payload.get("parameters") or {}
    sizes = set()
    for name in DRIVE_FIELDS:
        found = _SIZE.search(str(parameters.get(name) or ""))
        if found and "+" not in str(parameters.get(name)):
            sizes.add(laptops.megabytes(*found.groups()))
    if len(sizes) != 1:
        return {}
    size = sizes.pop()
    titled = laptops.titled_storage(str(fields.get("title") or ""))
    if titled and titled != {size}:
        return {}
    identity = fields.get("identity") or {}
    if identity.get(laptops.STORAGE_KEY) == size:
        return {}
    return {"identity": {**identity, laptops.STORAGE_KEY: size}}


LAPTOPS_RULESET = register(
    SOURCE,
    LAPTOPS_SLUG,
    Ruleset(
        version=LAPTOPS_VERSION,
        rules=(
            Rule(
                id="dateks-laptops-storage-from-its-drives",
                layer=SOURCE,
                why=(
                    "`Atmiņa > Iekšējā atmiņa` is a phone's storage and a laptop's working"
                    " memory at this shop — equal to `Operatīvā atmiņa` on 220 of the 234"
                    " laptops that carry it — so the category's rule, reading it as storage,"
                    " took nothing for 361 of 747. The drive is what `SSD` or `HDD` states,"
                    " one of them, and the title must not name another."
                ),
                body=_storage_from_its_drives,
            ),
        ),
    ),
)
