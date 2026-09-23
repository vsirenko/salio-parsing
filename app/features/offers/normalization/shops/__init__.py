"""Per-shop rulesets, imported for their side effect of registering themselves.

What a shop's codes and stock words mean is true in every category it sells, so it is
selected by the shop and not by the channel. A shop with no module here gets none of it,
which is how a new shop starts.
"""

from app.features.offers.normalization.shops import (
    bigbox,
    bm,
    dateks,
    discover,
    euronics,
    ksenukai,
    m79,
    mdata,
    onea,
    rdveikals,
    tet,
)

__all__ = (
    "bigbox",
    "bm",
    "dateks",
    "discover",
    "euronics",
    "ksenukai",
    "m79",
    "mdata",
    "onea",
    "rdveikals",
    "tet",
)
