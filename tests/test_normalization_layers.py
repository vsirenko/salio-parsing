"""Layered reading: what generic finds, what a shop's own rules add, and the seam between.

The rules for a source are asserted by name rather than only by effect: the point of
declaring them as objects is that the set an offer will get can be read before any of them
has run, and a test that only checks the output would not notice one going missing.
"""

import json
import pathlib

import pytest

from app.features.offers.normalization import barcodes, read, rules_for, version_for
from app.features.offers.normalization.rules import (
    BRAND,
    CATEGORY,
    FINISH,
    PRODUCT,
    SHOP,
    SOURCE,
    Vocabulary,
)

KSENUKAI = "ksenukai-phones"
PHONES = "phones"
FIXTURE = json.loads((pathlib.Path(__file__).parent / "fixtures/ksenukai_phones.json").read_text())


def item(external_id: str = "1102611") -> dict:
    """One real index record, flattened the way the channel hands it over."""
    from app.features.runs.channels.ksenukai import fields_of

    return fields_of(next(i for i in FIXTURE["items"] if str(i["id"]) == external_id))


# --- the rules are readable before anything runs ---


def test_a_key_with_no_rules_is_read_by_what_is_more_general():
    """Not a failure: it is how a sample gets loaded and measured before rules exist."""
    assert rules_for() == ()
    assert rules_for("nobody-has-written-this-one") == ()
    assert version_for("nobody-has-written-this-one") == "generic-3"
    assert version_for(category="televisions") == "generic-3"


def test_the_rules_an_offer_gets_can_be_listed_before_one_is_read():
    """The whole reason rules are objects rather than a chain of conditionals."""
    rules = rules_for(KSENUKAI, shop_slug="ksenukai", category=PHONES)
    assert [rule.id for rule in rules] == [
        "phones-color",
        "phones-color-from-title",
        "phones-storage",
        "ksenukai-barcode",
        # Within a layer the registry orders by id, not by where a rule was declared.
        "ksenukai-color-from-title",
        "ksenukai-model",
        "ksenukai-article-is-not-a-part-number",
        # Last of all: the model is what every layer before it worked out.
        "phones-model-does-not-repeat-the-maker",
        "phones-model-from-the-registry",
        "phones-model-without-a-trailing-colour",
    ]
    # General to specific: the category, then what is true of the shop, then of this
    # channel, and canonicalisation last.
    assert [rule.layer for rule in rules] == [
        CATEGORY,
        CATEGORY,
        CATEGORY,
        SHOP,
        SOURCE,
        SOURCE,
        FINISH,
        FINISH,
        FINISH,
        FINISH,
    ]


def test_the_layers_run_general_to_specific():
    """A brand is scoped to a category, and a line cannot be known until both are read."""
    assert CATEGORY < SOURCE < BRAND < PRODUCT < FINISH


def test_every_rule_says_why_it_exists():
    """A reason that restates the code explains nothing; one from the data can be argued."""
    for rule in rules_for(KSENUKAI, shop_slug="ksenukai", category=PHONES):
        assert len(rule.why) > 80, rule.id


def test_a_rule_can_be_declared_and_not_written():
    """A gap that is visible beats one that is not.

    Colour was the first of these and is no longer one: a shop that states it in a field
    rather than a title made it writable, and the rule now has a body. What is left is the
    same shape one layer down — Apple's market code could be collapsed, and doing it on the
    evidence in hand would be wrong on a larger corpus.
    """
    from app.features.offers.normalization import rules_for

    rules = {r.id: r for r in rules_for(None, category=PHONES, brand="apple")}
    collapse = rules["apple-collapse-market-code"]
    assert collapse.pending
    assert collapse.body is None
    assert collapse.apply({}, {}, Vocabulary()) == {}, "a pending rule changes nothing"
    # And the why says what would go wrong, not what the code would do.
    assert "storage" in collapse.why


def test_the_version_names_what_was_applied():
    """Composed rather than opaque, so a row can be attributed without a lookup."""
    assert version_for() == "generic-3"
    assert version_for(KSENUKAI, shop_slug="ksenukai") == "generic-3+ksenukai-shop-1+ksenukai-7"
    assert (
        version_for(KSENUKAI, shop_slug="ksenukai", category=PHONES)
        == "generic-3+phones-13+ksenukai-shop-1+ksenukai-7"
    )
    assert (
        read(item(), source_slug=KSENUKAI, shop_slug="ksenukai", category=PHONES)["ruleset_version"]
        == "generic-3+phones-13+ksenukai-shop-1+ksenukai-7"
    )


def test_the_capacity_is_read_as_an_exact_number():
    """Megabytes, not gigabytes: a 32 MB feature phone would otherwise be 0.03125 GB, and
    an identity axis that is a fraction is one that gets compared wrongly eventually."""
    fields = read(item(), source_slug=KSENUKAI, shop_slug="ksenukai", category=PHONES)
    assert fields["identity"]["storage_mb"] == 32

    big = read(item("1268710"), source_slug=KSENUKAI, shop_slug="ksenukai", category=PHONES)
    assert big["identity"]["storage_mb"] == 128 * 1024


def test_working_memory_is_not_capacity():
    """The silent wrong answer this rule exists to avoid.

    Both shops name working memory the same way and built-in capacity differently, and one
    of them writes the unit into the name — so an exact-name match found neither, fell
    through to the title, and read `12GB/512GB` as twelve gigabytes of storage.
    """
    payload = {
        "name": "Tālrunis Oukitel WP56 5G 12GB/512GB Black",
        "attributes": {"Operatīvā atmiņa, (RAM)": "12 GB", "Iekšējā atmiņa, GB": "512GB"},
    }
    assert read(payload, category=PHONES)["identity"]["storage_mb"] == 512 * 1024

    # And with no attribute at all, the larger of the two in the title.
    assert read({"name": payload["name"]}, category=PHONES)["identity"]["storage_mb"] == (
        512 * 1024
    )


def test_a_name_that_only_mentions_working_memory_is_refused():
    payload = {"name": "A phone", "attributes": {"Operatīvā atmiņa (RAM)": "8 GB"}}
    assert read(payload, category=PHONES)["identity"] == {}


def test_the_category_alone_reads_capacity_from_any_shop():
    """It is a property of the kind of product, not of where the listing came from."""
    fields = read({"name": "Some phone, 256 GB, black"}, category=PHONES)
    assert fields["identity"]["storage_mb"] == 256 * 1024
    # And the shop's own rules are what find the barcode, so they are still missing.
    assert fields["gtin"] is None


# --- what generic alone gets from this shop ---


def test_generic_alone_misses_what_matching_needs(client=None):
    """The measurement that says a source ruleset is needed at all."""
    fields = read(item())
    assert fields["title"].startswith("Telefons ar pogām MyPhone")
    assert fields["brand_raw"] == "MyPhone"
    assert fields["price"] is not None
    # The three that matter, and none of them found.
    assert fields["gtin"] is None
    assert fields["model"] is None
    assert fields["mpn"] is None


# --- what the shop's own rules add ---


def test_the_barcode_is_found_among_the_other_numbers():
    fields = read(item(), source_slug=KSENUKAI, shop_slug="ksenukai", category=PHONES)
    assert fields["gtin"] == "05902983617747"


def test_the_model_is_found_in_the_attribute_table():
    fields = read(item(), source_slug=KSENUKAI, shop_slug="ksenukai", category=PHONES)
    assert fields["model"] == "Hammer Rock"


def test_an_internal_article_number_is_not_a_part_number():
    """541 of 541 began `Y0000`, and the old system reported 100% MPN coverage for it."""
    fields = read(
        {**item(), "mpn": "Y00001210299"},
        source_slug=KSENUKAI,
        shop_slug="ksenukai",
        category=PHONES,
    )
    assert fields["mpn"] is None
    # A real one is left alone.
    kept = read(
        {**item(), "mpn": "SM-A576BLB"}, source_slug=KSENUKAI, shop_slug="ksenukai", category=PHONES
    )
    assert kept["mpn"] == "SM-A576BLB"


def test_a_rule_that_finds_nothing_erases_nothing():
    """A missing model must not wipe one generic happened to find."""
    payload = {**item(), "model": "Galaxy S24", "attributes": {}}
    assert (
        read(payload, source_slug=KSENUKAI, shop_slug="ksenukai", category=PHONES)["model"]
        == "Galaxy S24"
    )


def test_every_real_phone_in_the_fixture_reads(client=None):
    for record in FIXTURE["items"]:
        fields = read(
            item(str(record["id"])), source_slug=KSENUKAI, shop_slug="ksenukai", category=PHONES
        )
        assert fields["title"]
        assert fields["brand_raw"]
        assert fields["model"], record["id"]


# --- choosing a barcode ---


@pytest.mark.parametrize(
    "code, ok",
    [
        ("5902983617747", True),  # EAN-13
        ("590298361774", False),  # the same with its check digit lopped off
        ("036000291452", True),  # UPC-A
        # Used as a stand-in barcode all over this suite, and not a real one: its check
        # digit should be 6. Length alone never told us that.
        ("194253000001", False),
        ("4006381333931", True),  # EAN-13
        ("4006381333930", False),  # one digit wrong
        ("1226772", False),  # the shop's own product code
        ("Y00001210299", False),  # the shop's own article number
        ("", False),
    ],
)
def test_a_check_digit_decides(code, ok):
    assert barcodes.valid(code) is ok


def test_a_number_a_shop_assigned_itself_is_refused():
    """GS1 reserves these for in-store numbering: it can never agree with another shop."""
    assert barcodes.valid("2001234567893")
    assert barcodes.restricted("2001234567893")
    assert barcodes.pick(["2001234567893"]) is None


def test_a_barcode_is_one_code_however_many_digits_a_shop_writes():
    """`840493610849` at rdveikals and `0840493610849` at dateks are one Motorola; stored as
    written they were two barcodes and the rung missed between the two shops."""
    from app.features.offers.normalization import barcodes

    assert barcodes.pick("840493610849") == barcodes.pick("0840493610849") == "00840493610849"
    assert barcodes.pick("96385074") == "00000096385074"  # a GTIN-8, padded by the same rule
    assert barcodes.canonical("0840493610849") == "00840493610849"


def test_the_longer_of_two_forms_wins():
    """A shop listing both is listing an EAN and the same number without its check digit."""
    assert barcodes.pick(["590298361774", "05902983617747"]) == "05902983617747"


def test_nothing_valid_is_nothing():
    assert barcodes.pick(["1226772", "Y00001210299"]) is None
    assert barcodes.pick(None) is None
    assert barcodes.pick([]) is None


# --- the brand layer, selected from what was read ---


def test_the_brand_layer_selects_itself_from_the_reading():
    """Nothing passes the brand in. It is worked out from what the layers above found,
    which is why those layers come first."""
    fields = read(
        {"name": "Apple iPhone", "brand": "Apple", "mpn": "MG014HX/A"},
        category=PHONES,
    )
    assert fields["ruleset_version"] == "generic-3+phones-13+apple-phones-2"
    assert fields["identity"]["apple_config"] == "MG014"
    assert fields["identity"]["apple_market"] == "HX"


def test_two_markets_of_one_machine_share_a_configuration():
    """`MG014HX/A` and `MG014QN/A` are one phone sold in two places. Nine of ninety-six
    configurations in the collected corpus are split this way."""
    one = read({"name": "x", "brand": "Apple", "mpn": "MG014HX/A"}, category=PHONES)
    other = read({"name": "x", "brand": "Apple", "mpn": "MG014QN/A"}, category=PHONES)

    assert one["identity"]["apple_config"] == other["identity"]["apple_config"]
    assert one["identity"]["apple_market"] != other["identity"]["apple_market"]
    # And the part number each shop published is left exactly as it was.
    assert one["mpn"] != other["mpn"]


def test_a_brand_is_scoped_to_a_category():
    """`phones/apple` and `laptops/apple` are different rulesets. Nothing is registered for
    laptops, so the same offer read as one gets no brand rules at all."""
    payload = {"name": "x", "brand": "Apple", "mpn": "MG014HX/A"}
    assert read(payload, category="laptops")["identity"] == {}
    assert read(payload, category=PHONES)["identity"]["apple_config"] == "MG014"


def test_a_part_number_of_another_shape_is_left_alone():
    fields = read({"name": "x", "brand": "Apple", "mpn": "SOMETHING-ELSE"}, category=PHONES)
    assert "apple_config" not in fields["identity"]
    assert fields["mpn"] == "SOMETHING-ELSE"


def test_a_model_does_not_repeat_its_maker():
    """`Motorola Motorola G06 Power` is how 301 catalogue entries of 2939 came out: the
    title composes the brand and the model, and the model already held the brand. Which
    word is the maker is handed in, because no rule can know it and no shop says it."""
    from app.features.offers.normalization.rules import Vocabulary

    words = Vocabulary(brand_names=frozenset({"motorola", "samsung"}))
    fields = read(
        {"name": "Motorola Moto G06 Power", "brand": "Motorola", "model": "Motorola Moto G06"},
        category=PHONES,
        vocabulary=words,
    )
    assert fields["model"] == "Moto G06"

    # A catalogue with no brands in it hands in nothing, and then this does nothing.
    bare = read(
        {"name": "Motorola Moto G06", "brand": "Motorola", "model": "Motorola Moto G06"},
        category=PHONES,
    )
    assert bare["model"] == "Motorola Moto G06"


def test_a_maker_s_name_can_be_a_phrase_and_the_word_alone_is_not_the_unit():
    """`Cosmic Orange` and `Cosmic Black` share a word and are two colours, so Apple's
    palette is keyed on phrases. `titanium` used to win over both halves of these, which is
    why it is no longer a colour the registry holds."""
    desert = read(
        {"name": "Apple iPhone 16 Pro Max 256GB Desert Titanium", "brand": "Apple"},
        category=PHONES,
    )
    assert desert["identity"]["color"] == "gold"
    natural = read(
        {"name": "Apple iPhone 16 Pro 1TB Natural Titanium", "brand": "Apple"},
        category=PHONES,
    )
    assert natural["identity"]["color"] == "grey"


def test_the_titanium_phrases_the_shops_disagree_about_stay_unwritten():
    """`Lunar` gets four answers from four shops and `Stellar` three."""
    brand_rules = [r for r in rules_for(category=PHONES, brand="apple") if r.layer == BRAND]
    contested = next(r for r in brand_rules if r.id == "apple-contested-titanium")
    assert contested.pending
    fields = read(
        {"name": "Apple iPhone 17 Pro 512GB Lunar Titanium", "brand": "Apple"}, category=PHONES
    )
    assert "color" not in fields["identity"]


def test_a_maker_s_own_name_for_a_colour_is_read_in_its_own_layer():
    """`Canyon` is pink on a Google and orange on an Oppo, both unanimous across two shops.
    A registry row is keyed on the word with no brand and would have to make one of them
    wrong, so the palette lives where the brand selects it."""
    fields = read(
        {"name": "Google Pixel 11 Pro 12/256GB Canyon", "brand": "Google"}, category=PHONES
    )
    assert fields["identity"]["color"] == "pink"
    # And it cannot reach another maker: nothing is registered for Oppo.
    other = read({"name": "Oppo Reno16 5G 256GB Canyon", "brand": "Oppo"}, category=PHONES)
    assert "color" not in other["identity"]


def test_a_colour_the_shop_stated_itself_wins():
    """The shop answered about the product it is selling; the palette answers about a word."""
    fields = read(
        {
            "name": "Google Pixel 11 Pro 12/256GB Canyon",
            "brand": "Google",
            "specs": {"Krāsa": "melna"},
        },
        category=PHONES,
        vocabulary=Vocabulary(colours={"melna": "black"}, attribute_names={"krāsa": "color"}),
    )
    assert fields["identity"]["color"] == "black"


def test_two_of_the_maker_s_names_in_one_title_decide_nothing():
    """A two-tone phone or a bundle. Picking one of them is a wrong answer, not half of one."""
    fields = read({"name": "Google Pixel 11 Canyon Jade", "brand": "Google"}, category=PHONES)
    assert "color" not in fields["identity"]


def test_the_palette_matches_whole_words():
    fields = read({"name": "Google Pixel Fogo Edition 128GB", "brand": "Google"}, category=PHONES)
    assert "color" not in fields["identity"]


def test_the_decided_palette_words_are_marked_as_decided():
    """`frost` and `lemongrass` are in the palette by a decision, not by a count, and the
    rule that says so is declared with no body so nobody changes them without reading why:
    rdveikals reads Frost purple on 12 and euronics blue on 6, and the judge asked as a
    straight choice between those two answered neither, at 0.89."""
    brand_rules = [r for r in rules_for(category=PHONES, brand="google") if r.layer == BRAND]
    decided = next(r for r in brand_rules if r.id == "google-decided-by-hand")
    assert decided.pending
    frost = read({"name": "Google Pixel 11 12/256GB Frost", "brand": "Google"}, category=PHONES)
    assert frost["identity"]["color"] == "purple"
    lemongrass = read(
        {"name": "Google Pixel 10 12/128GB Lemongrass", "brand": "Google"}, category=PHONES
    )
    assert lemongrass["identity"]["color"] == "green"


def test_samsung_reads_its_maker_s_own_names_for_a_colour():
    """`Cobalt Violet` is purple in 9 shops of 9, 217 listings. The shops that state a
    colour in a field are the evidence for what the name means."""
    fields = read(
        {"name": "Samsung Galaxy S24 128GB Cobalt Violet", "brand": "Samsung"}, category=PHONES
    )
    assert fields["identity"]["color"] == "purple"


def test_a_name_that_contains_a_colour_word_is_not_read_as_that_colour():
    """`Blueberry` is purple, not blue, and `Graygreen` is green, not grey. A substring
    match would get both wrong with the confidence of a right answer."""
    blueberry = read(
        {"name": "Samsung Galaxy S26 FE 5G 256GB Blueberry (SM-S741B)", "brand": "Samsung"},
        category=PHONES,
    )
    assert blueberry["identity"]["color"] == "purple"
    graygreen = read(
        {"name": "Samsung Galaxy A37 5G 128GB Dual SIM Graygreen (SM-A376B)", "brand": "Samsung"},
        category=PHONES,
    )
    assert graygreen["identity"]["color"] == "green"


def test_a_shop_that_contradicts_itself_is_no_vote_at_all():
    """`Awesome Charcoal` looked like three shops for black against two for grey, until the
    votes were read: dateks says black on the Enterprise Edition of the A37 and grey on the
    plain one — the same phrase on the same phone. Without it, two shops to one."""
    fields = read(
        {"name": "Samsung Galaxy A37 5G 6+128GB Awesome Charcoal", "brand": "Samsung"},
        category=PHONES,
    )
    assert fields["identity"]["color"] == "black"


def test_the_name_with_one_shop_behind_it_is_declared_and_unwritten():
    brand_rules = [r for r in rules_for(category=PHONES, brand="samsung") if r.layer == BRAND]
    assert next(r for r in brand_rules if r.id == "samsung-pinkgold").pending


def test_a_maker_s_phrase_is_read_where_neither_half_is_a_colour():
    """`Dry Ice` is OnePlus's, and neither word names a colour on its own."""
    fields = read(
        {"name": "OnePlus Nord 5 5G 12/512GB Dual SIM Dry Ice", "brand": "OnePlus"},
        category=PHONES,
    )
    assert fields["identity"]["color"] == "blue"


def test_samsung_is_declared_and_unwritten():
    """Its trailing letters are half the product — colour tells two phones apart, region
    does not — so cutting them the way Apple's allow would merge different phones."""
    brand_rules = [r for r in rules_for(category=PHONES, brand="samsung") if r.layer == BRAND]
    part_number = next(r for r in brand_rules if r.id == "samsung-model-from-part-number")
    assert part_number.pending

    fields = read({"name": "x", "brand": "Samsung", "mpn": "SM-A176BZKAEUE"}, category=PHONES)
    assert fields["mpn"] == "SM-A176BZKAEUE"


def test_collapsing_apple_market_codes_is_declared_and_refused():
    """It would be correct on the collected data and wrong on a larger corpus, where three
    prefixes of sixty-six disagreed on storage — and the failure is two machines filed as
    one, confidently."""
    collapse = next(
        r for r in rules_for(category=PHONES, brand="apple") if r.id == "apple-collapse-market-code"
    )
    assert collapse.pending
    assert "three configuration prefixes out of sixty-six" in collapse.why


# --- a version that is not bumped is a fix that never arrives ---


# The fingerprint of each ruleset's rule bodies, as they are. A stored reading is recomputed
# only when its `ruleset_version` differs, so editing a rule and leaving the version alone
# is a fix that reaches nothing: the reparse sees the same string, keeps the old row, and
# the rule looks like it did not work. That happened three times in one afternoon.
#
# Changing a body changes the fingerprint and fails the test. Bump the version *and* put the
# new fingerprint here, in the same commit — two values that must move together, so
# forgetting one is loud instead of silent.
FINGERPRINTS = {
    "apple-phones-2": "f940eea49212",
    "bigbox-10": "4497939fdfce",
    "bigbox-shop-1": "a1194a23b2e7",
    "bigbox-tablets-4": "2cf6e57ea6f2",
    "bm-3": "3361a10390bd",
    "bm-shop-1": "3d09a6688700",
    "cec-1": "e0252dfe4696",
    "dateks-5": "0acd87a6666d",
    "dateks-shop-1": "76bf8766fb11",
    "dateks-tablets-1": "abe9d2e77bfe",
    "discover-5": "9d14cd5c199c",
    "discover-shop-1": "6065096d8d22",
    "discover-tablets-2": "1669cef96d6b",
    "euronics-shop-1": "07e9d1415e04",
    "euronics-tablets-1": "0deff7ac20bc",
    "google-phones-3": "b13ca41b33fa",
    "ksenukai-7": "c39ae807fae8",
    "ksenukai-shop-1": "b5a073020a15",
    "ksenukai-tablets-2": "160bac581cae",
    "m79-8": "43b109729576",
    "m79-shop-1": "ad962ef2618c",
    "m79-tablets-1": "ca0ff57d51a2",
    "mdata-3": "f9fdde9ae356",
    "mdata-shop-1": "c0edf1b90896",
    "onea-5": "b5c2de2bad0c",
    "onea-shop-1": "24e6184df567",
    "onea-tablets-2": "b700b4c0cd8b",
    "oneplus-phones-1": "29eaabd5e1ad",
    "phones-13": "8a8607df0554",
    "rdveikals-6": "01226413c43a",
    "rdveikals-shop-1": "e0b3a42600f7",
    "rdveikals-tablets-1": "1ae570d9626a",
    "samsung-phones-2": "9653d4e6a46a",
    "tablets-7": "f5adf534b922",
    "tet-3": "bd343fa22553",
    "tet-shop-1": "3129e8453377",
}


def _fingerprints() -> dict[str, str]:
    """A digest of the code each ruleset is made of — bodies *and* what they call.

    Hashing only the rule bodies was the first attempt and it missed the very change that
    prompted this: the capacity fix lived in `_megabytes`, a helper the body calls, so the
    fingerprint never moved. So every function the module defines is hashed, and the
    module-level constants they read — the regexes and the bounds, which decide as much as
    the code does.

    Prose is deliberately not hashed. A `why` is written inside the ruleset literal and
    editing one changes nothing about what a reading comes out as, so it should not force
    three thousand rows to be recomputed.

    The shared modules a ruleset imports are hashed with it — `models.py`, `colours.py`,
    `naming.py`, `barcodes.py`. Hashing the ruleset's own module alone missed the second
    change of the same kind: a guard added to `models.from_title` moved no fingerprint, and
    `phones` would have kept its version over a different reading. The framework — `rules`
    and the package itself — is left out: it is every ruleset's, and changing it already
    means the whole suite.
    """
    import hashlib
    import inspect
    import re

    from app.features.offers.normalization.rules import (
        BRANDS,
        CATEGORIES,
        PRODUCTS,
        SHOPS,
        SOURCES,
    )

    package = "app.features.offers.normalization"
    framework = {package, f"{package}.rules"}

    def shared(module) -> list:
        """The package's own modules this one imports, as modules or through a name."""
        found = set()
        for value in vars(module).values():
            other = value if inspect.ismodule(value) else inspect.getmodule(value)
            name = getattr(other, "__name__", "")
            if other is not module and name.startswith(package) and name not in framework:
                found.add(other)
        return sorted(found, key=lambda m: m.__name__)

    def hash_module(digest, module) -> None:
        for name, value in sorted(vars(module).items()):
            if inspect.isfunction(value) and inspect.getmodule(value) is module:
                digest.update(name.encode())
                digest.update(inspect.getsource(value).encode())
            elif isinstance(value, frozenset) and not name.startswith("__"):
                # Sorted: a set of strings iterates in an order that changes per process.
                digest.update(f"{name}={sorted(value, key=repr)!r}".encode())
            elif isinstance(value, (int, float, str, tuple)) and not name.startswith("__"):
                digest.update(f"{name}={value!r}".encode())
            elif isinstance(value, re.Pattern):
                digest.update(f"{name}={value.pattern!r}".encode())

    seen: dict[str, str] = {}
    for registry in (CATEGORIES, SHOPS, SOURCES, BRANDS, PRODUCTS):
        for ruleset in registry.values():
            bodies = [rule.body for rule in ruleset.rules if rule.body is not None]
            if not bodies:  # pragma: no cover - a ruleset of nothing but pending rules
                seen[ruleset.version] = "pending"
                continue

            module = inspect.getmodule(bodies[0])
            digest = hashlib.sha256()
            hash_module(digest, module)
            for other in shared(module):
                digest.update(other.__name__.encode())
                hash_module(digest, other)
            # The ids say which rules exist; the rest says what they do.
            digest.update(",".join(sorted(rule.id for rule in ruleset.rules)).encode())
            seen[ruleset.version] = digest.hexdigest()[:12]
    return seen


def test_a_changed_rule_body_carries_a_changed_version():
    seen = _fingerprints()
    stale = {
        version: (FINGERPRINTS[version], digest)
        for version, digest in seen.items()
        if version in FINGERPRINTS and FINGERPRINTS[version] != digest
    }
    assert not stale, (
        "a rule body changed under a version that did not: a reparse would keep every"
        " stored reading and the change would reach nothing. Bump the version and update"
        " FINGERPRINTS together.\n"
        + "\n".join(f"  {v}: recorded {was}, now {now}" for v, (was, now) in stale.items())
    )


def test_every_ruleset_is_fingerprinted():
    """A new ruleset with no entry here is one the guard above silently ignores."""
    missing = sorted(set(_fingerprints()) - set(FINGERPRINTS))
    assert not missing, f"rulesets with no recorded fingerprint: {missing}"


# --- taking a maker's name off the front of a shop's text ---


def test_a_brand_is_only_taken_off_when_it_is_the_whole_first_word():
    """`CAT` against `Caterpillar CAT S75` matched `startswith` and left `erpillar CAT S75`.

    A model with three letters missing off the front is worse than one with the brand still
    on it: it is wrong rather than untidy, and nothing downstream can tell.
    """
    from app.features.offers.normalization import naming

    assert naming.without_brand("Caterpillar CAT S75 6GB", "CAT") == "Caterpillar CAT S75 6GB"
    assert naming.without_brand("Honor 600 Lite, 8GB", "Honor") == "600 Lite, 8GB"
    assert naming.without_brand("HAMMER Hammer Iron 6", "HAMMER") == "Hammer Iron 6"
    # The shop naming a different maker than the name does is left alone, not guessed at.
    assert naming.without_brand("Google Pixel 10", "Getnord") == "Google Pixel 10"


def test_a_name_that_is_only_the_brand_is_left_alone():
    """Nothing is a worse model than something, so the name stands."""
    from app.features.offers.normalization import naming

    assert naming.without_brand("Apple", "Apple") == "Apple"
    assert naming.without_brand("", "Apple") == ""
    assert naming.without_brand("Apple iPhone", "") == "Apple iPhone"


# --- the model is the registry's spelling, found whole in the title ---


REGISTRY = {
    "samsung": {
        "galaxy s26": "Galaxy S26",
        "s26": "Galaxy S26",
        "galaxy s26+": "Galaxy S26+",
        "galaxy s26 ultra": "Galaxy S26 Ultra",
        "galaxy s26 ultra 5g": "Galaxy S26 Ultra",
        "galaxy a56": "Galaxy A56",
    },
    "xiaomi": {"redmi note 17": "Redmi Note 17"},
}


def test_the_model_is_the_registry_s_spelling_found_whole_in_the_title():
    """bm.market has no model field, and cutting the title before the first capacity leaves
    `Galaxy S26 S942 5G Dual Sim`, which named a catalogue entry. The name is in the title
    whole; the registry is what says which words it is."""
    words = Vocabulary(models=REGISTRY)
    fields = read(
        {
            "name": "Samsung Galaxy S26 S942 5G Dual Sim 12GB RAM 128GB - Cobalt Violet",
            "brand": "Samsung",
            "model": "Galaxy S26 S942 5G Dual Sim",
        },
        category=PHONES,
        vocabulary=words,
    )
    assert fields["model"] == "Galaxy S26"

    # A spelling the registry was told about, without the line's name in front of it.
    short = read(
        {"name": "Viedtālrunis Samsung S26 256GB SM-S942B Black", "brand": "Samsung"},
        category=PHONES,
        vocabulary=words,
    )
    assert short["model"] == "Galaxy S26"


def test_the_longest_known_name_wins_and_a_plus_is_a_different_phone():
    words = Vocabulary(models=REGISTRY)
    ultra = read(
        {"name": "Samsung Galaxy S26 Ultra 5G 256GB", "brand": "Samsung"},
        category=PHONES,
        vocabulary=words,
    )
    assert ultra["model"] == "Galaxy S26 Ultra"
    plus = read(
        {"name": "Samsung Galaxy S26+ (S947) (Silver Shadow) Dual SIM 6.7", "brand": "Samsung"},
        category=PHONES,
        vocabulary=words,
    )
    assert plus["model"] == "Galaxy S26+"


def test_a_known_name_the_title_carries_on_is_not_the_name_it_holds():
    """bm wrote `Apple iPhone 16 Pro 1TB`; the registry knew `iPhone 16` and not the Pro, and
    the longest known name filed seven Pro listings under the plain phone. A name followed by
    a variant word is a name the registry has not been given, so the shop's reading stands."""
    words = Vocabulary(models={"apple": {"iphone 16": "iPhone 16"}, **REGISTRY})
    pro = read(
        {"name": "Apple iPhone 16 Pro 1TB White Titanium", "brand": "Apple", "model": "as read"},
        category=PHONES,
        vocabulary=words,
    )
    assert pro["model"] == "as read"
    plain = read(
        {"name": "Apple iPhone 16 128GB Black", "brand": "Apple", "model": "as read"},
        category=PHONES,
        vocabulary=words,
    )
    assert plain["model"] == "iPhone 16"
    # Nor does a shorter name inside the refused one win in its place.
    zte = Vocabulary(models={"zte": {"blade": "Blade", "blade v70": "Blade V70"}})
    max_ = read(
        {"name": "ZTE Blade V70 Max 8/256GB", "brand": "ZTE", "model": "as read"},
        category=PHONES,
        vocabulary=zte,
    )
    assert max_["model"] == "as read"
    # A shop writing the plus twice has not named a second phone.
    twice = read(
        {"name": "Samsung Galaxy S26+ Plus 5G 512GB Black", "brand": "Samsung"},
        category=PHONES,
        vocabulary=words,
    )
    assert twice["model"] == "Galaxy S26+"


def test_a_title_naming_two_models_keeps_what_the_shop_s_rule_read():
    """A bundle, or a listing that names two phones: picking one is a wrong answer rather
    than half of one, so the reading the layers before this one produced stands."""
    fields = read(
        {"name": "Samsung Galaxy S26 + Galaxy A56", "brand": "Samsung", "model": "as read"},
        category=PHONES,
        vocabulary=Vocabulary(models=REGISTRY),
    )
    assert fields["model"] == "as read"


def test_a_stated_maker_opens_only_its_own_page():
    """The shop said Xiaomi, so Samsung's names are not consulted — whatever the title says."""
    fields = read(
        {"name": "Xiaomi Galaxy S26 lookalike 128GB", "brand": "Xiaomi", "model": "as read"},
        category=PHONES,
        vocabulary=Vocabulary(models=REGISTRY),
    )
    assert fields["model"] == "as read"


def test_a_maker_the_shop_did_not_state_is_found_through_every_page():
    """m79's German feed states no maker at all. Every page is consulted, and one answer
    from one maker is an answer."""
    fields = read(
        {"name": 'Xiaomi Redmi Note 17 | Sky Teal | 6.99 " | 2396 x 1080 pixels'},
        category=PHONES,
        vocabulary=Vocabulary(models=REGISTRY),
    )
    assert fields["model"] == "Redmi Note 17"


def test_a_stated_maker_with_no_page_is_not_read_through_another_maker_s():
    """ZTE has no page and Hammer's holds `Blade`; reading every page for a stated maker
    filed four different ZTE phones under one Hammer name."""
    fields = read(
        {"name": "ZTE Blade A31 lite 32GB", "brand": "ZTE", "model": "as read"},
        category=PHONES,
        vocabulary=Vocabulary(
            models={"hammer": {"blade": "Blade"}, **REGISTRY}, brand_names=frozenset({"zte"})
        ),
    )
    assert fields["model"] == "as read"
    # A brand field that names no maker we know says nothing, and every page is read.
    unknown = read(
        {"name": "Samsung Galaxy S26 5G 256GB", "brand": "Samsung Smartphone", "model": "x"},
        category=PHONES,
        vocabulary=Vocabulary(models=REGISTRY, brand_names=frozenset({"samsung"})),
    )
    assert unknown["model"] == "Galaxy S26"


def test_a_colour_left_on_the_end_of_a_model_comes_off():
    """bm has no model field and `Cat S31 Black` no capacity to cut at, so the colour stayed
    on the model and named the entry."""
    words = Vocabulary(colours={"black": "black", "grey": "grey"})
    for name, model in (
        ("Cat S31 Black", "S31"),
        ("Samsung Galaxy S10 Lite Grey", "Galaxy S10 Lite"),
    ):
        fields = read(
            {"name": name, "model": name.split(" ", 1)[1]}, category=PHONES, vocabulary=words
        )
        assert fields["model"] == model, name
    # Never the last word, and never one the registry was not given.
    alone = read({"name": "Black", "model": "Black"}, category=PHONES, vocabulary=words)
    assert alone["model"] == "Black"
    kept = read(
        {"name": "Ulefone Armor Mini", "model": "Armor Mini"}, category=PHONES, vocabulary=words
    )
    assert kept["model"] == "Armor Mini"


def test_a_field_is_the_attribute_the_registry_says_it_is():
    """Resolved exactly, not by fragment. rdveikals files storage under a section called
    `Procesors un operatīvā atmiņa (RAM)`, and the fragment `ram` threw its storage away as
    working memory; `ram` also sits inside `paRAMetri` and `PRogRAMmatūra`."""
    words = Vocabulary(
        attribute_names={
            "procesors un operatīvā atmiņa (ram) / telefona iebūvēta atmiņa": "storage_mb",
            "procesors un operatīvā atmiņa (ram) / operatīvā atmiņa (ram)": "ram_mb",
        }
    )
    fields = read(
        {
            "name": "Phone X",
            "specs": {
                "Procesors un operatīvā atmiņa (RAM) / Operatīvā atmiņa (RAM)": "12 GB",
                "Procesors un operatīvā atmiņa (RAM) / Telefona iebūvēta atmiņa": "512 GB",
            },
        },
        category=PHONES,
        vocabulary=words,
    )
    assert fields["identity"]["storage_mb"] == 512 * 1024
    # A name the registry was not given is not read at all, however storage-like it sounds.
    unknown = read({"name": "Phone X", "specs": {"Internal memory": "256 GB"}}, category=PHONES)
    assert "storage_mb" not in unknown["identity"]


def test_a_capacity_the_sources_disagree_on_is_not_read():
    """Title and field disagreed 38 times in 5188 and the market sided with each about as
    often, so neither is ranked: a disagreement reads as nothing."""
    words = Vocabulary(attribute_names={"atmiņa": "storage_mb", "krātuve": "storage_mb"})

    def storage(name, specs):
        return read({"name": name, "specs": specs}, category=PHONES, vocabulary=words)[
            "identity"
        ].get("storage_mb")

    # rdveikals: the field says 1 GB for a 1 TB phone.
    assert storage("Apple iPhone Air 1TB Space Black", {"Atmiņa": "1 GB"}) is None
    # Agreeing sources are taken; a field alone and a title alone are each enough.
    assert storage("Phone 256GB", {"Atmiņa": "256 GB"}) == 256 * 1024
    assert storage("Phone", {"Atmiņa": "128 GB"}) == 128 * 1024
    assert storage("Phone 64GB", {}) == 64 * 1024
    # dateks: two datasheets disagree, and the title settles which one is right.
    assert storage("Galaxy A37 8GB/256GB", {"Atmiņa": "128 GB", "Krātuve": "256 GB"}) == 256 * 1024
    assert storage("MyPhone FLIP LTE", {"Atmiņa": "48 MB", "Krātuve": "128 MB"}) is None


def test_with_no_registry_the_shop_s_reading_stands():
    fields = read(
        {"name": "Samsung Galaxy S26 S942 5G Dual Sim", "brand": "Samsung", "model": "as read"},
        category=PHONES,
    )
    assert fields["model"] == "as read"
