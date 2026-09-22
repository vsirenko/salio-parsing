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


def from_title(title: str, names: Mapping[str, str]) -> str | None:
    """The longest of a maker's names found whole in the title, or nothing.

    Whole words only, in order: `galaxy s26` is found in `Samsung Galaxy S26 S942 5G Dual
    Sim` and not in `Galaxy S26+ 256GB`, because there the word is `s26+`. That is what lets
    `+` tell two phones apart, and why a substring match would not do.

    Longest wins, so `Galaxy S26 Ultra` beats the `Galaxy S26` inside it and `Pixel 10 Pro
    XL` beats `Pixel 10`. Two *different* names of the same length decide nothing: that is a
    bundle — `Galaxy S23 + Watch 5` — or a listing naming two phones, and picking one is a
    wrong answer rather than half of one.

    Every window of up to `LONGEST_MODEL_NAME` words is looked up, rather than every alias
    tried against the title: a few hundred lookups per title however large the registry.
    """
    if not title or not names:
        return None
    try:
        words = normalize_model_name(title).split()
    except ValueError:
        return None

    longest = 0
    found: set[str] = set()
    for start in range(len(words)):
        for length in range(1, min(LONGEST_MODEL_NAME, len(words) - start) + 1):
            model = names.get(" ".join(words[start : start + length]))
            if model is None:
                continue
            if length > longest:
                longest, found = length, {model}
            elif length == longest:
                found.add(model)
    return found.pop() if len(found) == 1 else None
