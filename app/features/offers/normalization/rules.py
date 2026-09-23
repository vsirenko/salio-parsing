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
    SHOP       the shop                          what its codes and stock words mean
    SOURCE     the channel                       how it names this category's products
    BRAND      (category, brand)                 this maker's conventions
    PRODUCT    (category, brand, line)           one line's own habits
    FINISH     nothing                           check digits, reserved prefixes, canon

Three things that ordering encodes, and each was learned the expensive way somewhere:

- **The category comes before the shop.** The same shape of code means different things to
  a laptop and a monitor, and keeping their rules in one list means applying the wrong one
  eventually.
- **The shop comes before the channel.** A shop's barcodes, part numbers and stock words
  mean the same whichever of its categories a listing is in; how it writes a product's name
  may not. Filed under the channel, the first were lost to every new category of the same
  shop, which would have been read worse than its phones on its first day.
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

from app.features.attributes.normalization import normalize_attribute_name

GENERIC, CATEGORY, SHOP, SOURCE, BRAND, PRODUCT, FINISH = 10, 20, 25, 30, 40, 50, 90


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
    # Every maker the catalogue knows, lowercased. A model does not repeat its maker, and
    # a shop that states no brand field leaves it on the model instead — `Samsung Galaxy S26
    # Ultra 5G` where every other shop writes `Galaxy S26 Ultra 5G`. Which word is the maker
    # is not something a rule can know and not something a shop tells us, so it is handed
    # in, like the words for `phone` above.
    brand_names: frozenset[str] = frozenset()
    # Every spelling of a colour that resolves, lowercased, to the canonical value it means:
    # `melna` and `black` both to `black`. One map for every language the registry holds,
    # because a rule reading a Latvian field and a rule reading an English name are both
    # asking the same question and neither should carry the answer.
    colours: Mapping[str, str] = MappingProxyType({})
    # What each maker calls what it makes: keyed by the maker as `normalize_brand` spells
    # it, then by a spelling as `normalize_model_name` spells it, to the name the catalogue
    # uses. `{"samsung": {"galaxy s26": "Galaxy S26", "s26": "Galaxy S26"}}`. The reader
    # finds the longest of these whole in a title, which is what makes twelve shops arrive
    # at one name — and it is data, because which words are a model is the same kind of
    # fact as which words are a colour, and a rule that carried them would carry a shop's.
    models: Mapping[str, Mapping[str, str]] = MappingProxyType({})
    # What each shop calls an attribute of this category, as `normalize_attribute_name`
    # spells it, to the attribute's key: `iekšējā atmiņa gb` and `storage_capacity` both to
    # `storage_mb`. Scoped to the category, because the same name can be two attributes in
    # two categories, and a name that is two attributes in one is left out rather than
    # guessed. Exact, not a fragment: `ram` inside `paRAMetri` once hid rdveikals' storage.
    attribute_names: Mapping[str, str] = MappingProxyType({})
    # What a shop writes as the value of one of this category's attributes, to the value it
    # means, by the attribute's key: `{"connectivity": {"nē": "wifi", "ir": "cellular"}}`.
    # The words for yes and no are Latvian facts, and four shops answer "has it a modem?"
    # with them — `4G savienojums: Nē`, `Mobilie sakari: Ir` — so they are rows, not code.
    values: Mapping[str, Mapping[str, str]] = MappingProxyType({})

    def attribute_key(self, name: str) -> str | None:
        """Which of our attributes a shop's name for one is, or nothing."""
        try:
            return self.attribute_names.get(normalize_attribute_name(name))
        except ValueError:
            return None

    def value_of(self, key: str, text: str) -> str | None:
        """The value a shop's word for one of an attribute's values means, or nothing."""
        try:
            return self.values.get(key, {}).get(normalize_attribute_name(text))
        except ValueError:
            return None


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
SHOPS: dict[str, Ruleset] = {}
SOURCES: dict[str, Ruleset] = {}
BRANDS: dict[tuple[str, str], Ruleset] = {}
PRODUCTS: dict[tuple[str, str, str], Ruleset] = {}

_REGISTRIES: dict[int, dict] = {
    CATEGORY: CATEGORIES,
    SHOP: SHOPS,
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
