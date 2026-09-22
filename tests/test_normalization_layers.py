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
    assert version_for("nobody-has-written-this-one") == "generic-1"
    assert version_for(category="televisions") == "generic-1"


def test_the_rules_an_offer_gets_can_be_listed_before_one_is_read():
    """The whole reason rules are objects rather than a chain of conditionals."""
    rules = rules_for(KSENUKAI, category=PHONES)
    assert [rule.id for rule in rules] == [
        "phones-color",
        "phones-storage",
        "ksenukai-barcode",
        # Within a layer the registry orders by id, not by where a rule was declared.
        "ksenukai-color-from-title",
        "ksenukai-model",
        "ksenukai-article-is-not-a-part-number",
    ]
    # General to specific: the category before the shop, canonicalisation last.
    assert [rule.layer for rule in rules] == [
        CATEGORY,
        CATEGORY,
        SOURCE,
        SOURCE,
        SOURCE,
        FINISH,
    ]


def test_the_layers_run_general_to_specific():
    """A brand is scoped to a category, and a line cannot be known until both are read."""
    assert CATEGORY < SOURCE < BRAND < PRODUCT < FINISH


def test_every_rule_says_why_it_exists():
    """A reason that restates the code explains nothing; one from the data can be argued."""
    for rule in rules_for(KSENUKAI, category=PHONES):
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
    assert version_for() == "generic-1"
    assert version_for(KSENUKAI) == "generic-1+ksenukai-5"
    assert version_for(KSENUKAI, category=PHONES) == "generic-1+phones-5+ksenukai-5"
    assert (
        read(item(), source_slug=KSENUKAI, category=PHONES)["ruleset_version"]
        == "generic-1+phones-5+ksenukai-5"
    )


def test_the_capacity_is_read_as_an_exact_number():
    """Megabytes, not gigabytes: a 32 MB feature phone would otherwise be 0.03125 GB, and
    an identity axis that is a fraction is one that gets compared wrongly eventually."""
    fields = read(item(), source_slug=KSENUKAI, category=PHONES)
    assert fields["identity"]["storage_mb"] == 32

    big = read(item("1268710"), source_slug=KSENUKAI, category=PHONES)
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
    fields = read(item(), source_slug=KSENUKAI, category=PHONES)
    assert fields["gtin"] == "5902983617747"


def test_the_model_is_found_in_the_attribute_table():
    fields = read(item(), source_slug=KSENUKAI, category=PHONES)
    assert fields["model"] == "Hammer Rock"


def test_an_internal_article_number_is_not_a_part_number():
    """541 of 541 began `Y0000`, and the old system reported 100% MPN coverage for it."""
    fields = read({**item(), "mpn": "Y00001210299"}, source_slug=KSENUKAI, category=PHONES)
    assert fields["mpn"] is None
    # A real one is left alone.
    kept = read({**item(), "mpn": "SM-A576BLB"}, source_slug=KSENUKAI, category=PHONES)
    assert kept["mpn"] == "SM-A576BLB"


def test_a_rule_that_finds_nothing_erases_nothing():
    """A missing model must not wipe one generic happened to find."""
    payload = {**item(), "model": "Galaxy S24", "attributes": {}}
    assert read(payload, source_slug=KSENUKAI, category=PHONES)["model"] == "Galaxy S24"


def test_every_real_phone_in_the_fixture_reads(client=None):
    for record in FIXTURE["items"]:
        fields = read(item(str(record["id"])), source_slug=KSENUKAI, category=PHONES)
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


def test_the_longer_of_two_forms_wins():
    """A shop listing both is listing an EAN and the same number without its check digit."""
    assert barcodes.pick(["590298361774", "5902983617747"]) == "5902983617747"


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
    assert fields["ruleset_version"] == "generic-1+phones-5+apple-phones-1"
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


def test_samsung_is_declared_and_unwritten():
    """Its trailing letters are half the product — colour tells two phones apart, region
    does not — so cutting them the way Apple's allow would merge different phones."""
    brand_rules = [r for r in rules_for(category=PHONES, brand="samsung") if r.layer == BRAND]
    assert [r.id for r in brand_rules] == ["samsung-model-from-part-number"]
    assert brand_rules[0].pending

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
    "apple-phones-1": "12a9fce3575e",
    "bigbox-4": "c8d0450d4ad8",
    "bm-2": "df8fb9de5bff",
    "cec-1": "e0252dfe4696",
    "dateks-2": "28ca1e200e23",
    "ksenukai-5": "89aa740d025f",
    "onea-1": "3f30745390d5",
    "euronics-1": "e61bf95a7a78",
    "phones-5": "431fc8bf0c77",
    "rdveikals-4": "f5078e0afc82",
    "samsung-phones-0": "pending",
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
    """
    import hashlib
    import inspect
    import re

    from app.features.offers.normalization.rules import BRANDS, CATEGORIES, PRODUCTS, SOURCES

    seen: dict[str, str] = {}
    for registry in (CATEGORIES, SOURCES, BRANDS, PRODUCTS):
        for ruleset in registry.values():
            bodies = [rule.body for rule in ruleset.rules if rule.body is not None]
            if not bodies:  # pragma: no cover - a ruleset of nothing but pending rules
                seen[ruleset.version] = "pending"
                continue

            module = inspect.getmodule(bodies[0])
            digest = hashlib.sha256()
            for name, value in sorted(vars(module).items()):
                if inspect.isfunction(value) and inspect.getmodule(value) is module:
                    digest.update(name.encode())
                    digest.update(inspect.getsource(value).encode())
                elif isinstance(value, (int, float, str, tuple, frozenset)) and not name.startswith(
                    "__"
                ):
                    digest.update(f"{name}={value!r}".encode())
                elif isinstance(value, re.Pattern):
                    digest.update(f"{name}={value.pattern!r}".encode())
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
