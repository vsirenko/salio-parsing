"""Reading a raw payload into the fields the pipeline works on.

A pure function of the payload and the rules that apply to it, and that purity is what the
whole design rests on: improving a rule means re-running it over what is already stored and
comparing the old reading with the new one before accepting it. Nothing here touches the
database, and nothing here resolves a string to a row — a brand string becomes a brand
during matching, not here.

Layered general to specific, and what changes down the list is what selects each layer:
see `rules.py`. A key with no ruleset is read by whatever is more general, which is not a
failure — it is how a sample gets loaded and measured before any rules are written for it,
and the coverage on its run is what says which rules to write.
"""

from typing import Any

from app.features.brands.normalization import normalize_brand
from app.features.offers.normalization import generic
from app.features.offers.normalization.categories import __all__ as _categories  # noqa: F401
from app.features.offers.normalization.generic import content_hash
from app.features.offers.normalization.rules import (
    BRANDS,
    CATEGORIES,
    PRODUCTS,
    SOURCES,
    Rule,
    Ruleset,
)
from app.features.offers.normalization.sources import __all__ as _sources  # noqa: F401

# What a payload with no rules of its own is read by. Bumped whenever the generic reading
# changes; stored on every row it produces, so two readings of the same bytes can be told
# apart and compared.
RULESET_VERSION = generic.RULESET_VERSION

__all__ = [
    "RULESET_VERSION",
    "Rule",
    "Ruleset",
    "content_hash",
    "read",
    "rules_for",
    "version_for",
]


def _applicable(
    *, category: str | None, source_slug: str | None, brand: str | None, line: str | None
) -> list[Ruleset]:
    """The rulesets that apply, general first.

    Selection deepens down the list: a category is named by the channel, a brand is worked
    out from what has been read, and a line from what the brand's rules made of it.
    """
    found = [
        CATEGORIES.get(category or ""),
        SOURCES.get(source_slug or ""),
        BRANDS.get((category or "", brand or "")),
        PRODUCTS.get((category or "", brand or "", line or "")),
    ]
    return [ruleset for ruleset in found if ruleset is not None]


def rules_for(
    source_slug: str | None = None,
    *,
    category: str | None = None,
    brand: str | None = None,
    line: str | None = None,
) -> tuple[Rule, ...]:
    """Which rules these offers get — answerable without reading one.

    The reason rules are objects. A chain of conditionals answers the same question only by
    being run, and then only for the offer that happened to be tried.
    """
    rules = [
        rule
        for ruleset in _applicable(
            category=category, source_slug=source_slug, brand=brand, line=line
        )
        for rule in ruleset.rules
    ]
    return tuple(sorted(rules, key=lambda rule: (rule.layer, rule.id)))


def version_for(
    source_slug: str | None = None,
    *,
    category: str | None = None,
    brand: str | None = None,
    line: str | None = None,
) -> str:
    """What produced, or would produce, a reading.

    Composed rather than opaque: `generic-1+phones-1+ksenukai-1` says which three things
    were applied and in what order, so a row can be attributed without looking anything up.
    """
    parts = [RULESET_VERSION] + [
        ruleset.version
        for ruleset in _applicable(
            category=category, source_slug=source_slug, brand=brand, line=line
        )
    ]
    return "+".join(parts)


def read(
    payload: dict[str, Any],
    *,
    source_slug: str | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    """One reading of one payload. Everything it cannot make sense of stays None.

    The brand and the product line are not passed in: they are worked out from what the
    earlier layers read, which is why those layers come last. A rule that needs to name a
    line writes `_line` into the reading, and every key beginning with an underscore is
    working state that is dropped before anything is stored.
    """
    fields = generic.read(payload)
    fields.setdefault("identity", {})

    brand: str | None = None
    line: str | None = None
    for rule in rules_for(source_slug, category=category, brand=brand, line=line):
        # Each rule sees what the ones before it tidied, and later wins. A rule that finds
        # nothing returns nothing rather than a None that would erase an earlier answer.
        fields.update(rule.apply(payload, fields))
        if brand is None:
            brand = _brand_key(fields)
        line = fields.get("_line") or line

    # Recomputed once the earlier layers have run, so the brand's and the line's own rules
    # are picked up on this pass rather than on a second one.
    brand = _brand_key(fields)
    line = fields.get("_line") or line
    for rule in rules_for(source_slug, category=category, brand=brand, line=line):
        if rule.layer >= 40:  # BRAND and below: the layers that could not be selected yet
            fields.update(rule.apply(payload, fields))

    fields["ruleset_version"] = version_for(source_slug, category=category, brand=brand, line=line)
    return {key: value for key, value in fields.items() if not key.startswith("_")}


def _brand_key(fields: dict[str, Any]) -> str | None:
    """The brand as the alias table spells it, or nothing.

    The same function the aliases were stored with. Anything else here would look up a
    string nobody wrote down, which is the quiet way to have rules that never fire.
    """
    raw = fields.get("brand_raw")
    if not raw:
        return None
    try:
        return normalize_brand(str(raw))
    except ValueError:
        return None
