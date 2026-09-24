"""Per-category rulesets, imported for their side effect of registering themselves.

A category is a module of its own rather than a branch in a shared file, because the same
shape of value means different things to different kinds of product: `128 GB` is an
identity axis for a phone and a footnote for a television. Keeping their rules in one list
means applying the wrong one eventually.
"""

from app.features.offers.normalization.categories import laptops, phones, tablets

__all__ = ("laptops", "phones", "tablets")
