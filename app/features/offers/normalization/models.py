"""Finding the name a maker gave a model inside whatever a shop wrote around it.

The same reason `colours.py` exists: every channel meets this and none of them invented it.
Two shops here have no model field at all, and their rules cut the model out of the title
by subtraction — everything before the first capacity — which leaves whatever the shop put
in between: `Galaxy S26 S942 5G Dual Sim`, `razr fold 20.6 cm Dual SIM Android 16.0`. Of
1524 catalogue entries, 211 were named that way, 170 of them by those two shops.

Subtraction cannot be made clean, because the list of things to cut is open. Recognition
can: a title either holds a name the registry knows or it does not. Nothing here knows a
model. The whole vocabulary is in `model_aliases`, handed in through the `Vocabulary`, and
this only decides *which window of the title to look up*.
"""

from collections.abc import Mapping

from app.features.brands.normalization import LONGEST_MODEL_NAME, normalize_model_name

# The words a maker adds to a name to make another phone of the same line. A known name the
# title carries on with one of these is not the name the title holds: `iPhone 16` inside
# `iPhone 16 Pro` is the sibling, and reading it as the name filed seven Pro listings under
# the plain phone before this was checked. Not vocabulary in the sense `reading.md` means:
# a maker's variant word is the same word in every language, and what it does to a name —
# makes it another one — is true of every maker.
VARIANT_WORDS = frozenset(
    {
        "pro",
        "max",
        "ultra",
        "plus",
        "fold",
        "flip",
        "fe",
        "lite",
        "mini",
        "neo",
        "edge",
        "power",
        "xl",
        "prime",
    }
)


def from_title(title: str, names: Mapping[str, str]) -> str | None:
    """The longest of a maker's names found whole in the title, or nothing."""
    return longest_in_title(title, names)[0]


def longest_in_title(title: str, names: Mapping[str, str]) -> tuple[str | None, int]:
    """The longest of a maker's names found whole in the title, and how many words it is.

    Whole words only, in order: `galaxy s26` is found in `Samsung Galaxy S26 S942 5G Dual
    Sim` and not in `Galaxy S26+ 256GB`, because there the word is `s26+`. That is what lets
    `+` tell two phones apart, and why a substring match would not do.

    Longest wins, so `Galaxy S26 Ultra` beats the `Galaxy S26` inside it and `Pixel 10 Pro
    XL` beats `Pixel 10`. Two *different* names of the same length decide nothing: that is a
    bundle — `Galaxy S23 + Watch 5` — or a listing naming two phones, and picking one is a
    wrong answer rather than half of one.

    A name the title carries on with a variant word is not found there at all: `iPhone 16
    Pro` does not hold `iPhone 16`, it holds a name the registry has not been given. Nothing
    is the answer then, and the shop's own reading stands — a gap in the registry shows up as
    a gap rather than as the neighbouring phone.

    Every window of up to `LONGEST_MODEL_NAME` words is looked up, rather than every alias
    tried against the title: a few hundred lookups per title however large the registry.
    """
    if not title or not names:
        return None, 0
    try:
        words = normalize_model_name(title).split()
    except ValueError:
        return None, 0

    longest = 0
    found: set[str] = set()
    # Words inside a name the title carries on with a variant word. The shorter names within
    # it are not found either: with `blade v70` refused in `Blade V70 Max`, `blade` would
    # otherwise win and the reading would lose the half it had.
    # Only windows lying wholly inside one: `galaxy s26 ultra` overlaps the refused `galaxy
    # s26` in `Galaxy S26 Ultra 5G` and is exactly the name the title holds.
    refused: list[range] = []
    for start in range(len(words)):
        for length in range(1, min(LONGEST_MODEL_NAME, len(words) - start) + 1):
            window = " ".join(words[start : start + length])
            if window in names and _continued(words, start + length):
                refused.append(range(start, start + length))
    for start in range(len(words)):
        for length in range(1, min(LONGEST_MODEL_NAME, len(words) - start) + 1):
            model = names.get(" ".join(words[start : start + length]))
            end = start + length
            if model is None or any(r.start <= start and end <= r.stop for r in refused):
                continue
            if length > longest:
                longest, found = length, {model}
            elif length == longest:
                found.add(model)
    return (found.pop(), longest) if len(found) == 1 else (None, longest)


def _continued(words: list[str], end: int) -> bool:
    """Whether the word after a window makes the name another phone.

    `Galaxy S26+ Plus` is the one exception: a shop that writes the plus twice has not named
    a second model, so a `plus` after a name already ending in one continues nothing.
    """
    if end >= len(words):
        return False
    following = words[end].rstrip("+")
    if following not in VARIANT_WORDS:
        return False
    return not (following == "plus" and words[end - 1].endswith(("+", "plus")))
