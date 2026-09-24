"""Per-brand rulesets, one package per category.

A brand is scoped to a category rather than global, which is why they nest this way:
`phones/apple` and `laptops/apple` are different rulesets. That an Apple part number looks
like `XXXXXYY/A` is true of Apple everywhere; that a screen diagonal is part of the name is
true only of a MacBook Pro. Keeping them in one module would mean applying one shape of
knowledge to a machine it was never about.
"""

from app.features.offers.normalization.brands import laptops, phones, tablets

__all__ = ("laptops", "phones", "tablets")
