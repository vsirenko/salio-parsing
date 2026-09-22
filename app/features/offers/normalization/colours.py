"""Turning a colour phrase into a canonical value, once, for every shop.

The same reason `barcodes.py` exists: every channel meets this and none of them invented
it, so deciding it separately in each would mean deciding it differently in each.

Nothing here knows a colour. The whole vocabulary is in `attribute_value_aliases`, with the
language it belongs to, and this only decides *which part of a phrase to look up*.
"""

import re

from app.features.offers.normalization.rules import Vocabulary

# `(melns)`, `„mint green“`, `black (open box)`. Brackets and quotation marks are a
# shop's punctuation around a word, never part of the word — the same reason an
# attribute alias is stored without them.
_WRAPPED = re.compile(r"[(\[{][^)\]}]*[)\]}]")
_EDGES = re.compile(r"^[^\w]+|[^\w]+$")
# Quotation marks travel inside the phrase rather than around it — `krāsa „mint green“`
# — so they come out wherever they are.
_QUOTES = re.compile(r"[\u201e\u201c\u201d\u00ab\u00bb\"']")


def resolve(phrase: str, vocabulary: Vocabulary) -> str | None:
    """The canonical value a phrase names, or nothing.

    Tried whole first, then by dropping words off the front. That is what lets
    `lieliski pelēka` resolve — Samsung's `Awesome` line, translated — without this module
    holding a list of marketing prefixes, which would be vocabulary in code and Latvian at
    that. It works because in both languages here the colour is the head of the phrase and
    the head comes last: `midnight black`, `icy blue`, `tumši zila`.

    It does not work the other way round, and deliberately is not made to: `silver shadow`
    and `night sky` put the invented word last, and guessing from the first word instead
    would read `arctic seal` as a colour. They stay unresolved, which is the same answer
    this reading gives everywhere it is not sure.
    """
    if not phrase or not vocabulary.colours:
        return None

    # A bracketed aside is dropped whole; what is left keeps its own edges tidy. `(melns)`
    # is a colour in brackets, and `black (open box)` is a colour with a note after it.
    cleaned = _QUOTES.sub("", phrase)
    cleaned = _WRAPPED.sub(" ", cleaned) if _WRAPPED.search(cleaned) else cleaned
    cleaned = _EDGES.sub("", cleaned.strip()) or _EDGES.sub("", phrase.strip())

    words = cleaned.casefold().split()
    for start in range(len(words)):
        found = vocabulary.colours.get(" ".join(words[start:]))
        if found:
            return found
    return None


def pair(parts: list[str], vocabulary: Vocabulary) -> str | None:
    """Two colours written as one, the way a two-tone case is: `melna krās./oranža krās.`.

    A pairing the registry has never agreed to is not a colour — inventing `black-teal`
    here would put a value in a reading that nothing else in the system knows. Half a pair
    is not an answer either: it is the wrong colour rather than a partial one.
    """
    named = [resolve(part, vocabulary) for part in parts]
    if not named or any(value is None for value in named):
        return None
    if len(named) == 1:
        return named[0]

    canonical = "-".join(named)
    return canonical if canonical in set(vocabulary.colours.values()) else None
