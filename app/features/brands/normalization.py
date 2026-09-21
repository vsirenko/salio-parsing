"""Turning what a source wrote into what we match on.

The split that matters: what a rule can compute is computed and never stored, what no rule
derives is a row. Case, punctuation and a legal suffix are the first kind — `SAMSUNG®`,
`Samsung` and `Samsung Electronics Co., Ltd.` are one alias, not three. A declension is the
second: `Samsungo -> Samsung` is a fact somebody established, because Lithuanian declines
foreign names as a matter of grammar rather than as a spelling mistake.
"""

import re
import unicodedata

# Longest first, so "Co., Ltd." is taken before "Ltd". The Baltic three are here for the
# same reason the German and English ones are: they arrive in real feeds.
LEGAL_SUFFIXES = (
    "co., ltd.",
    "co ltd",
    "gmbh & co. kg",
    "s.p.a.",
    "a/s",
    "sia",
    "uab",
    "oü",
    "ltd.",
    "ltd",
    "llc",
    "inc.",
    "inc",
    "gmbh",
    "ag",
    "as",
    "bv",
    "b.v.",
    "nv",
    "n.v.",
    "sa",
    "s.a.",
    "srl",
    "oy",
    "ab",
    "plc",
    "kft",
    "sp. z o.o.",
    "d.o.o.",
)

TRADEMARKS = "®™©"
_PUNCTUATION_EDGES = " \t\n .,;:!-–—_/\\|\"'`«»"


def normalize_brand(value: str) -> str:
    """The form an alias is stored and looked up as.

    Raises when nothing is left, because a blank alias would match every offer whose brand
    field is a stray punctuation mark.
    """
    # NFKC first: a feed may send a full-width or composed character that looks identical
    # and compares unequal.
    text = unicodedata.normalize("NFKC", value)
    text = "".join(ch for ch in text if ch not in TRADEMARKS)
    text = re.sub(r"[\s ]+", " ", text).strip().lower()
    text = _strip_legal_suffix(text)
    text = text.strip(_PUNCTUATION_EDGES)

    if not text:
        raise ValueError("nothing left after normalization")
    return text


def _strip_legal_suffix(text: str) -> str:
    """Remove one trailing legal form, if the string is more than that form.

    Three conditions, and every one of them is load-bearing.

    **At the end only.** "AS" is a legal form in Estonia and Norway and a fine start to a
    brand name, so a match anywhere would eat "AS Tallinna".

    **A word of its own.** Without a boundary check, "Samsungas" — the Lithuanian
    declension of Samsung — loses its ending to that same "AS" and silently becomes a
    different string. So would Saab, to "AB".

    **Something has to be left.** A brand actually called "AS" keeps its name.
    """
    for suffix in LEGAL_SUFFIXES:
        if not text.endswith(suffix):
            continue
        head = text[: -len(suffix)]
        if not head or not (head[-1].isspace() or head[-1] in ",.-"):
            continue
        candidate = head.strip(_PUNCTUATION_EDGES)
        if candidate:
            return candidate
    return text
