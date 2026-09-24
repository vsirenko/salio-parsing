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
from app.features.offers.normalization.brands import __all__ as _brands  # noqa: F401
from app.features.offers.normalization.categories import __all__ as _categories  # noqa: F401
from app.features.offers.normalization.generic import content_hash
from app.features.offers.normalization.rules import (
    BRANDS,
    CATEGORIES,
    LAYER_NAMES,
    PRODUCTS,
    SHOPS,
    SOURCES,
    Rule,
    Ruleset,
    Vocabulary,
)
from app.features.offers.normalization.shops import __all__ as _shops  # noqa: F401
from app.features.offers.normalization.sources import __all__ as _sources  # noqa: F401

# What a payload with no rules of its own is read by. Bumped whenever the generic reading
# changes; stored on every row it produces, so two readings of the same bytes can be told
# apart and compared.
RULESET_VERSION = generic.RULESET_VERSION

__all__ = [
    "RULESET_VERSION",
    "Rule",
    "Ruleset",
    "Vocabulary",
    "content_hash",
    "read",
    "rules_for",
    "version_for",
]


def _applicable(
    *,
    category: str | None,
    shop_slug: str | None,
    source_slug: str | None,
    brand: str | None,
    line: str | None,
) -> list[Ruleset]:
    """The rulesets that apply, general first.

    Selection deepens down the list: a category is named by the channel, a brand is worked
    out from what has been read, and a line from what the brand's rules made of it.
    """
    found = [
        CATEGORIES.get(category or ""),
        SHOPS.get(shop_slug or ""),
        SOURCES.get(source_slug or ""),
        BRANDS.get((category or "", brand or "")),
        PRODUCTS.get((category or "", brand or "", line or "")),
    ]
    return [ruleset for ruleset in found if ruleset is not None]


def rules_for(
    source_slug: str | None = None,
    *,
    shop_slug: str | None = None,
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
            category=category,
            shop_slug=shop_slug,
            source_slug=source_slug,
            brand=brand,
            line=line,
        )
        for rule in ruleset.rules
    ]
    return tuple(sorted(rules, key=lambda rule: (rule.layer, rule.id)))


def version_for(
    source_slug: str | None = None,
    *,
    shop_slug: str | None = None,
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
            category=category,
            shop_slug=shop_slug,
            source_slug=source_slug,
            brand=brand,
            line=line,
        )
    ]
    return "+".join(parts)


def read(
    payload: dict[str, Any],
    *,
    source_slug: str | None = None,
    shop_slug: str | None = None,
    category: str | None = None,
    vocabulary: Vocabulary | None = None,
    trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One reading of one payload. Everything it cannot make sense of stays None.

    With `trace`, every step is appended to it as it runs — the generic read, then each
    rule with its layer, its `why` and exactly what it changed — so the path from a shop's
    fields to a reading can be shown rather than guessed at. The reading is the same either
    way: the trace watches, it decides nothing.

    The brand and the product line are not passed in: they are worked out from what the
    earlier layers read, which is why those layers come last. A rule that needs to name a
    line writes `_line` into the reading, and every key beginning with an underscore is
    working state that is dropped before anything is stored.
    """
    fields = generic.read(payload)
    fields.setdefault("identity", {})
    if trace is not None:
        trace.append(
            {
                "rule": "generic",
                "layer": "generic",
                "round": 1,
                "why": "What every payload is read for before any rule selected by it runs.",
                "changed": {key: [None, value] for key, value in fields.items() if value},
            }
        )
    # Handed in rather than looked up, so this stays a pure function of its arguments and a
    # reading can be recomputed over stored bytes and compared with the old one.
    words = vocabulary or Vocabulary()

    brand: str | None = None
    line: str | None = None
    for rule in rules_for(
        source_slug, shop_slug=shop_slug, category=category, brand=brand, line=line
    ):
        # Each rule sees what the ones before it tidied, and later wins. A rule that finds
        # nothing returns nothing rather than a None that would erase an earlier answer.
        _apply(rule, payload, fields, words, trace, 1)
        if brand is None:
            brand = _brand_key(fields)
        line = fields.get("_line") or line

    # Recomputed once the earlier layers have run, so the brand's and the line's own rules
    # are picked up on this pass rather than on a second one.
    brand = _brand_key(fields)
    line = fields.get("_line") or line
    for rule in rules_for(
        source_slug, shop_slug=shop_slug, category=category, brand=brand, line=line
    ):
        if rule.layer >= 40:  # BRAND and below: the layers that could not be selected yet
            _apply(rule, payload, fields, words, trace, 2)

    fields["ruleset_version"] = version_for(
        source_slug, shop_slug=shop_slug, category=category, brand=brand, line=line
    )
    return {key: value for key, value in fields.items() if not key.startswith("_")}


def _apply(
    rule: Any,
    payload: dict[str, Any],
    fields: dict[str, Any],
    words: Vocabulary,
    trace: list[dict[str, Any]] | None,
    run: int,
) -> None:
    """One rule's changes onto the reading, and onto the trace what they were."""
    found = rule.apply(payload, fields, words)
    if trace is not None:
        trace.append(
            {
                "rule": rule.id,
                "layer": LAYER_NAMES.get(rule.layer, str(rule.layer)),
                "round": run,
                "why": rule.why,
                "changed": _changes(fields, found),
            }
        )
    fields.update(found)


def _changes(before: dict[str, Any], found: dict[str, Any]) -> dict[str, list[Any]]:
    """What a rule's answer changes, key by key, `[before, after]`; an axis by its own key."""
    changed: dict[str, list[Any]] = {}
    for key, after in found.items():
        was = before.get(key)
        if key == "identity" and isinstance(after, dict):
            old = was if isinstance(was, dict) else {}
            for axis in sorted(set(old) | set(after)):
                if old.get(axis) != after.get(axis):
                    changed[f"identity.{axis}"] = [old.get(axis), after.get(axis)]
        elif was != after:
            changed[key] = [was, after]
    return changed


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
