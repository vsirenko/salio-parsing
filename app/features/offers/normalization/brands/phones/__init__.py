"""Brands as they behave in phones.

Imported for the side effect of registering. A brand with no module here is read by the
category and the shop alone, which is not a failure — it is every brand until somebody
measures one.
"""

from app.features.offers.normalization.brands.phones import apple, google, oneplus, samsung

__all__ = ("apple", "google", "oneplus", "samsung")
