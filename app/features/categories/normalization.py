"""Canonicalising a name a shop gives a category.

Separate from the brand and attribute normalizers rather than shared with them, because
they are not the same rule: a brand loses its legal suffix, an attribute loses a comma that
was holding a unit, and a category name loses neither — it is one or two plain words with
the shop's own punctuation around it.
"""

import re
import unicodedata

_COLLAPSE = re.compile(r"[\s ]+")
_EDGES = re.compile(r"^[^\w]+|[^\w]+$")


def normalize_category_name(value: str) -> str:
    """`„Telefons“` and `Telefons,` to one string.

    Diacritics survive, for the same reason they do elsewhere: folding `tālrunis` to
    `talrunis` merges words that only look alike to somebody who does not read the
    language, and a wrong merge costs more than a missed one.
    """
    text = unicodedata.normalize("NFKC", str(value))
    text = _COLLAPSE.sub(" ", text).strip()
    text = _EDGES.sub("", text).strip().casefold()
    if not text:
        raise ValueError("a category name cannot be empty once normalized")
    return text[:200]
