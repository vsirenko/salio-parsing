"""m79: what its codes and stock words mean, in every category it sells.

Moved out of `sources/m79.py` on 23.09.2026, when a second category made the
difference matter: these rules are true of the shop, and a new category of it would
otherwise have been read without them. How the shop names a product stays there.
"""

from typing import Any

from app.features.offers.normalization import barcodes
from app.features.offers.normalization.rules import (
    SHOP,
    Rule,
    Ruleset,
    Vocabulary,
    register,
)

SLUG = "m79"
VERSION = "m79-shop-1"


# Both of the shop's words mean it can be bought. `Ir noliktavā` is the warehouse and
# `Ir veikalā` the shop floor — a difference in where it sits, not in whether it is there.
IN_STOCK = ("Ir noliktavā", "Ir veikalā")


# The shop's own join id, which names a row in its import and nothing in the world. 1837 of
# the 2700 codes are one, and putting one on `mpn` would be a part number that can never
# agree with another shop's.
INTERNAL = "JOINEDIT"


def _barcode(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    return {"gtin": barcodes.pick(payload.get("barcodes"))}


def _part_number(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The shop's item code, when it is the maker's and not the shop's own."""
    code = str(payload.get("code") or "").strip()
    if not code or code.upper().startswith(INTERNAL):
        return {}
    # A code that is the barcode is already recorded as one. Recording it twice would put a
    # barcode on the part number rung, where it would match things a barcode never would.
    if code == fields.get("gtin") or code.isdigit():
        return {}
    return {"mpn": code[:100]}


def _availability(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    flag = str(payload.get("availability") or "").strip()
    return {"availability": "in_stock"} if flag in IN_STOCK else {}


RULESET = register(
    SHOP,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="m79-barcode",
                layer=SHOP,
                why=(
                    "There is no barcode field on this shop anywhere — not on the card, not"
                    " on the product page. What there is is the address:"
                    " `…-smf966bzsbeue-8806097423720-joinedit96318361`. The channel hands"
                    " the digit runs over as a list and `barcodes.pick` chooses, as it does"
                    " for every shop, and on 2700 collected products that yields a valid"
                    " code for 1947 of them — 72%, higher than all but two of the other"
                    " ten. The number in the image address is **not** it: on 34 sampled"
                    " cards it was 13 digits once and the shop's own id the other 33 times,"
                    " which is why the channel does not collect it."
                ),
                body=_barcode,
            ),
            Rule(
                id="m79-part-number",
                layer=SHOP,
                why=(
                    "`data-itemid` is base64 and the channel decodes it, but what comes out"
                    " is three different things depending on the supplier: Samsung's"
                    " `SM-A576BZABEUE`, Spigen's `ACS04816`, a bare barcode, or the shop's"
                    " own `JOINEDIT96318361`. The last is 1837 of the 2700 and names a row"
                    " in this shop's import rather than anything in the world — on `mpn` it"
                    " would be a part number that can never agree with another shop's, and"
                    " the part number rung would gain 1837 dead ends. Digits are dropped"
                    " for the opposite reason: they are already the barcode, and the same"
                    " value on two rungs makes the weaker one look as strong as the"
                    " stronger. What is left is 743 real part numbers."
                ),
                body=_part_number,
            ),
            Rule(
                id="m79-availability",
                layer=SHOP,
                why=(
                    "Two words and no third: `Ir noliktavā` on 2667 of 2700 and `Ir veikalā`"
                    " on 33. Both mean it can be bought — one is the warehouse and the other"
                    " the shop floor — so this shop states where a thing is rather than"
                    " whether it is there. It publishes nothing it has not got, which is why"
                    " there is no out-of-stock word to read; if one ever appears it will"
                    " read as `unknown` and be visible, which is the right way round."
                ),
                body=_availability,
            ),
        ),
    ),
)
