"""The form an attribute name is stored and looked up as.

Its own module because two features need it and they must agree: the registry stores an
alias through it, and the reading looks a shop's name up through it. A lookup that
normalized differently would miss, and a missed name reads as a shop that never said.
"""

import re


def normalize_attribute_name(value: str) -> str:
    """What an alias is stored and matched as.

    Case and punctuation are noise every source adds differently, so they are computed away
    rather than stored as separate rows: `Krāsa`, `krāsa` and `Krāsa:` are one alias, not
    three.

    A comma inside the name is the same noise one step in, and it took two real shops to
    notice: one writes `Operatīvā atmiņa (RAM)` and the other `Operatīvā atmiņa, (RAM)`,
    one writes `Ekrāna izmērs` and the other `Ekrāna izmērs, "` — a unit appended to the
    name of the thing. Left alone each spelling is a row of its own and a lookup has to
    guess which it will meet. A comma separates a qualifier a shop tacked on, never two
    names, so it becomes a space and whatever mark it was holding up goes with it.
    """
    cleaned = re.sub(r"[,;]", " ", value)
    cleaned = re.sub(r"[\s\u00a0]+", " ", cleaned).strip().strip(":.,;®™").strip()
    # `ekrāna izmērs "` — the unit the comma was holding on. A closing bracket survives,
    # because `(RAM)` is part of the name rather than a decoration on it.
    cleaned = re.sub(r"[^\w)]+$", "", cleaned).strip()
    if not cleaned:
        raise ValueError("an alias cannot be blank")
    return cleaned.lower()
