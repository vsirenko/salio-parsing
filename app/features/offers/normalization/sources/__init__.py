"""Per-source rulesets, imported for their side effect of registering themselves.

A shop with no module here is read generically, which is not a failure — it is how a
sample gets loaded and measured before any rules are written for it.
"""

from app.features.offers.normalization.sources import (
    bigbox,
    bigbox_laptops,
    bm,
    bm_laptops,
    cec,
    cec_laptops,
    dateks,
    dateks_laptops,
    discover,
    discover_laptops,
    euronics,
    euronics_laptops,
    ksenukai,
    m79,
    mdata,
    onea,
    rdveikals,
    rdveikals_laptops,
    tet,
)

__all__ = (
    "bigbox",
    "bigbox_laptops",
    "bm",
    "bm_laptops",
    "cec",
    "cec_laptops",
    "dateks",
    "dateks_laptops",
    "discover",
    "discover_laptops",
    "euronics",
    "euronics_laptops",
    "ksenukai",
    "m79",
    "mdata",
    "onea",
    "rdveikals",
    "rdveikals_laptops",
    "tet",
)
