"""Taking a maker's name off the front of a shop's own text.

Here rather than in each ruleset for the reason `barcodes.py` is: it is one decision that
every shop needs and that every shop would otherwise make separately and differently. It
was written twice — once for dateks and once for bm.market — and both copies had the same
fault, which is the argument for there being one copy.

The fault: a brand is taken off by length, so `CAT` against `Caterpillar CAT S75` matched
`startswith` and left `erpillar CAT S75`. A model with three letters missing from the front
of it is worse than one with the brand still on, because it is wrong rather than untidy and
nothing downstream can tell.
"""

import re

# What may follow the brand for it to have been the whole first word: a space, a comma, a
# dash, a slash — or nothing at all, when the name is only the brand.
_BOUNDARY = re.compile(r"^[\s,./|-]")
_EDGES = re.compile(r"^[\s,./|-]+|[\s,./|-]+$")


def without_brand(name: str, brand: str) -> str:
    """`name` with `brand` taken off the front, or `name` unchanged.

    Unchanged when the name does not begin with the brand, and unchanged when it begins
    with a longer word that merely starts the same way — which is the whole point of this
    living in one place.
    """
    name = (name or "").strip()
    brand = (brand or "").strip()
    if not name or not brand:
        return name
    if not name.casefold().startswith(brand.casefold()):
        return name

    rest = name[len(brand) :]
    if rest and not _BOUNDARY.match(rest):
        return name
    return _EDGES.sub("", rest) or name
