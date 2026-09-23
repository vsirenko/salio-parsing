"""Whether a card in a phone category is a tablet.

Two shops file tablets among their phones, and a tablet that becomes a phone entry cannot be
told from a real one afterwards: `Blackview Active 7 Wi-Fi + 4G 11` was named, priced and
compared as a phone. Measured over the 9096 collected listings on 23.09.2026, six were
tablets and every pattern below took all six and no phone.

Three signals, because no one of them is enough. The word, in the languages these feeds are
written in. `Wi-Fi + 4G`, which is how a tablet sells its cellular version and no phone
describes itself. And the maker's tablet lines — `iPad`, `Galaxy Tab`, `MatePad`, and a
`…Pad` followed by a model number or word, which is what keeps `Motorola Edge 70 Lily Pad`, a
colour, out of it.
"""

import re

_WORD = re.compile(r"\b(?:tablet|tabletti|planšet\w*|planšetinis|tahvelarvuti)\b", re.IGNORECASE)
_CELLULAR = re.compile(r"\bWi-?Fi\s*\+\s*(?:4G|LTE|5G|Cellular)\b", re.IGNORECASE)
_LINE = re.compile(
    r"\b(?:iPad|Galaxy Tab|MatePad|Tab\s?[A-Z0-9]"
    r"|[A-Za-z]*Pad(?:\s?\d|\s+(?:SE|Pro|Air|Mini|Plus|Ultra|Lite|Neo)\b))"
)


def is_a_tablet(name: str) -> bool:
    return bool(_WORD.search(name) or _CELLULAR.search(name) or _LINE.search(name))
