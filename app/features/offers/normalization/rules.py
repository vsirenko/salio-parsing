"""A rule as an object: what it is for, which offers it touches, and when its turn is.

The point of declaring them rather than writing one long function is that the set of rules
an offer will get can be read **before** any of them has run. A chain of conditionals only
answers that question by being executed, and then only for the offer you happened to try.

Five layers, general to specific, each seeing what the ones before it tidied. What changes
down the list is not only how specific the knowledge is but **what selects it**:

    layer      selected by                       reading
    ────────   ───────────────────────────────   ────────────────────────────────────
    GENERIC    nothing                           any flat payload: known key names
    CATEGORY   the category                      what this kind of product means
    SOURCE     the channel                       where this shop hides things
    BRAND      (category, brand)                 this maker's conventions
    PRODUCT    (category, brand, line)           one line's own habits
    FINISH     nothing                           check digits, reserved prefixes, canon

Three things that ordering encodes, and each was learned the expensive way somewhere:

- **The category comes before the shop.** The same shape of code means different things to
  a laptop and a monitor, and keeping their rules in one list means applying the wrong one
  eventually.
- **The shop comes before the brand**, because a brand knows more about its own product
  than any shop does and should see a string the shop's rules have already tidied.
- **A brand is scoped to a category, not global.** `phones/apple` and `laptops/apple` are
  different rulesets: that a part number looks like `XXXXXYY/A` is true of Apple
  everywhere, but that a screen diagonal is part of the name is true only of a MacBook Pro.

`PRODUCT` is selected from what the layers above produced, which is why it is last before
canonicalisation: a line cannot be known until the brand and the model have been read. A
rule writes that key into the reading as `_line`, and every key starting with an underscore
is working state that `read` drops before anything is stored.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

GENERIC, CATEGORY, SOURCE, BRAND, PRODUCT, FINISH = 10, 20, 30, 40, 50, 90


@dataclass(frozen=True)
class Vocabulary:
    """The words a rule needs and cannot know, handed in rather than looked up.

    `read` is a pure function of a payload and the rules that apply to it, and that purity
    is what lets a reading be recomputed over stored bytes and compared with the old one.
    A rule that queried a registry would break it, and a rule that carried the words itself
    would put Latvian in a module and Lithuanian in the same module a month later.

    So the caller loads them and passes them. Empty is a valid vocabulary: a rule that
    needs words it was not given does nothing, which is a rule declining to guess.
    """

    # What shops call this category, normalized: `telefons`, `viedtālrunis`, `mobilais`.
    # A shop puts one at the front of a title and it carries no model.
    category_names: frozenset[str] = frozenset()
    # Every spelling of a colour that resolves, lowercased, to the canonical value it means:
    # `melna` and `black` both to `black`. One map for every language the registry holds,
    # because a rule reading a Latvian field and a rule reading an English name are both
    # asking the same question and neither should carry the answer.
    colours: Mapping[str, str] = MappingProxyType({})


# What a rule is handed: the raw payload, the reading so far, and the words it was given.
Body = Callable[[dict[str, Any], dict[str, Any], Vocabulary], dict[str, Any]]


@dataclass(frozen=True)
class Rule:
    """One named change to a reading.

    `why` is the case from the data that put it there, not a restatement of the code. A
    rule whose reason is "normalises the model" explains nothing; one that says "this
    shop's article numbers all begin Y0000 and match no other shop" can be argued with.
    """

    id: str
    layer: int
    why: str
    body: Body | None = None

    @property
    def pending(self) -> bool:
        """Declared but not written. A gap that is visible beats one that is not."""
        return self.body is None

    def apply(
        self, payload: dict[str, Any], fields: dict[str, Any], vocabulary: Vocabulary
    ) -> dict[str, Any]:
        return {} if self.body is None else self.body(payload, fields, vocabulary)


@dataclass(frozen=True)
class Ruleset:
    """Everything one key contributes, and the version it contributes under."""

    version: str
    rules: tuple[Rule, ...] = field(default_factory=tuple)

    def ordered(self) -> tuple[Rule, ...]:
        return tuple(sorted(self.rules, key=lambda rule: (rule.layer, rule.id)))


# One registry per layer that has a key. A key with no entry is not a failure: it is how a
# sample gets loaded and measured before any rules are written for it.
CATEGORIES: dict[str, Ruleset] = {}
SOURCES: dict[str, Ruleset] = {}
BRANDS: dict[tuple[str, str], Ruleset] = {}
PRODUCTS: dict[tuple[str, str, str], Ruleset] = {}

_REGISTRIES: dict[int, dict] = {
    CATEGORY: CATEGORIES,
    SOURCE: SOURCES,
    BRAND: BRANDS,
    PRODUCT: PRODUCTS,
}


def register(layer: int, key: Any, ruleset: Ruleset) -> Ruleset:
    registry = _REGISTRIES[layer]
    if key in registry:
        raise ValueError(f"a ruleset is already registered for {key!r}")
    registry[key] = ruleset
    return ruleset
