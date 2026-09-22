"""Per-source rulesets, imported for their side effect of registering themselves.

A shop with no module here is read generically, which is not a failure — it is how a
sample gets loaded and measured before any rules are written for it.
"""

from app.features.offers.normalization.sources import bigbox, ksenukai, rdveikals

__all__ = ("bigbox", "ksenukai", "rdveikals")
