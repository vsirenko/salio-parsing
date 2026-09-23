"""Choosing a barcode out of whatever a shop calls its codes.

Shops mix barcodes with their own numbering in one list and do not say which is which.
Deciding belongs here rather than in a parser: a check digit and a reserved prefix are a
standard, so every channel would otherwise implement the same rule separately and
differently — and a parser that decided would bake its answer into the only copy of the
bytes there is.
"""

import re

_DIGITS = re.compile(r"\D")
# GS1 reserves these for numbers a shop assigns itself: they identify something inside one
# retailer and nothing outside it. Accepting one would put a private number on the
# strongest signal the matcher has, where it can never agree with another shop and will
# occasionally agree with the wrong one.
RESTRICTED = ("02", "04", "2")
VALID_LENGTHS = (8, 12, 13, 14)


def valid(code: str) -> bool:
    """A GTIN-8, UPC-A, EAN-13 or GTIN-14 whose check digit agrees with the rest."""
    digits = _DIGITS.sub("", str(code))
    if len(digits) not in VALID_LENGTHS or not digits.isdigit():
        return False
    body, check = digits[:-1], int(digits[-1])
    # Weights alternate 3 and 1 from the right, whatever the length.
    total = sum(
        int(digit) * (3 if index % 2 == 0 else 1) for index, digit in enumerate(reversed(body))
    )
    return (10 - total % 10) % 10 == check


def restricted(code: str) -> bool:
    digits = _DIGITS.sub("", str(code))
    return digits.startswith(RESTRICTED)


# Every barcode is stored as a GTIN-14, zero-padded. A UPC-A and the EAN-13 it becomes with
# a leading zero are one code — `840493610849` at rdveikals and `0840493610849` at dateks are
# one Motorola — and 229 of 2736 distinct codes were read both ways on 23.09.2026, so the
# barcode rung missed between exactly the shops that wrote them differently. Padding is the
# standard's own rule for comparing GTINs of different lengths, and it loses nothing.
CANONICAL_LENGTH = 14


def canonical(code: str) -> str:
    """The one form a barcode is stored and compared in."""
    return _DIGITS.sub("", str(code)).zfill(CANONICAL_LENGTH)


def pick(candidates: object) -> str | None:
    """The one real barcode in a list, or nothing.

    Longest first, because a shop that lists both `590298361774` and `5902983617747` is
    listing an EAN-13 and the same number with its check digit lopped off — and only the
    longer one is the barcode other shops will also have.
    """
    if candidates is None:
        return None
    values = candidates if isinstance(candidates, list | tuple) else [candidates]
    found = [
        _DIGITS.sub("", str(value)) for value in values if valid(value) and not restricted(value)
    ]
    return canonical(max(found, key=len)) if found else None
