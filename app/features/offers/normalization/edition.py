"""The edition a device is sold as: an axis of its own, as the glass is.

Samsung sells most of its phones and tablets a second time as an Enterprise Edition — the
same hardware with longer updates and a business warranty, under barcodes and part numbers
of its own and at its own price: on 26.09.2026 1a.lv and Ksenukai asked 1459 € for an S26
Ultra 256 EE against 1039 € for the ordinary one. It is another entry of the same family,
not another family, and not the same entry. Its own module, as `glass.py` is: phones and
tablets both read it.

A category's rule and not Samsung's brand layer, though it is Samsung's alone: the brand
layer is chosen by the shop's brand field, and m79 and bm leave it empty on 583 Samsung
phones whose brand is only found later, from the title. So the rule asks whether the listing
is a Samsung itself, as the glass asks whether it is an Apple.
"""

import re
from typing import Any

from app.features.offers.normalization.rules import Vocabulary

EDITION_KEY = "edition"
STANDARD = "standard"
ENTERPRISE = "enterprise"

# `Enterprise Edition`, the maker's words, the same in every language — and m79's
# `Xcover 7 Pro 5G 6GB/128GB Enterprise (Black)`, which leaves the second one off.
_ENTERPRISE = re.compile(r"\benterprise\b", re.IGNORECASE)
# bigbox's `… 256 GB EE DS Graphite` and m79's `(12GB) EE DE Model`: the abbreviation as a word
# of its own, in capitals. Lower case is a word in some language, not the edition.
_EE = re.compile(r"(?<![\w-])EE(?![\w-])")
# Samsung's part number ends in three region letters, and an Enterprise Edition's begin with
# `EE`: `SM-S948BZKDEEE`, `SM-X356BZGAEEB`, `SM-X306BZGAEEA`, against `…EUE` and `…EUB`.
_EE_PART_NUMBER = re.compile(r"\bSM-?[A-Z]\d{3}[A-Z0-9]*EE[A-Z]\b", re.IGNORECASE)
_SAMSUNG = re.compile(r"\bsamsung\b", re.IGNORECASE)
_EDITION_WORDS = re.compile(r"\s*(?:\b(?i:enterprise(?:\s+edition)?)\b|(?<![\w-])EE(?![\w-]))")


def the_edition(
    payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
) -> dict[str, Any]:
    """The edition on the identity, and no word about it left on the model.

    Enterprise where the title, the model or the part number says so, standard everywhere
    else: a listing of the Enterprise Edition says it, somewhere, because it is what the
    price is for — and one that says it only in its barcode is placed by the barcode.
    """
    if not _SAMSUNG.search(f"{fields.get('brand_raw') or ''} {fields.get('title') or ''}"):
        return {}
    model = str(fields.get("model") or "").strip()
    text = " ".join(str(fields.get(key) or "") for key in ("title", "mpn")) + " " + model
    enterprise = bool(_ENTERPRISE.search(text) or _EE.search(text) or _EE_PART_NUMBER.search(text))
    edition = ENTERPRISE if enterprise else STANDARD
    found: dict[str, Any] = {}
    identity = dict(fields.get("identity") or {})
    if identity.get(EDITION_KEY) != edition:
        found["identity"] = {**identity, EDITION_KEY: edition}
    bare = " ".join(_EDITION_WORDS.sub(" ", model).split())
    if model and bare and bare != model:
        found["model"] = bare
    return found
