"""Brands, their aliases, and what a string resolves to."""

import pytest

from app.features.brands.normalization import normalize_brand
from tests.test_auth import ADMIN, CUSTOMER, auth, tokens


def admin_token(client) -> str:
    return tokens(client, ADMIN, panel="/admin")["access_token"]


def add_brand(client, token, slug, name):
    response = client.post(
        "/api/admin/brands", headers=auth(token), json={"slug": slug, "canonical_name": name}
    )
    assert response.status_code == 201, response.text
    return response.json()


def add_alias(client, token, brand_id, alias, kind="spelling"):
    return client.post(
        f"/api/admin/brands/{brand_id}/aliases",
        headers=auth(token),
        json={"alias": alias, "kind": kind},
    )


# --- normalization is a function, not rows ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Samsung", "samsung"),
        ("SAMSUNG", "samsung"),
        (" samsung ", "samsung"),
        ("Samsung®", "samsung"),
        ("Bosch GmbH", "bosch"),
        ("Ekspla UAB", "ekspla"),
        ("Rīgas Elektronika SIA", "rīgas elektronika"),
        ("Tallink OÜ", "tallink"),
        ("Elgiganten AB", "elgiganten"),
        ("Samsung Electronics Co., Ltd.", "samsung electronics"),
        # A legal form is only stripped at the end: AS starts plenty of real names.
        ("AS Tallinna", "as tallinna"),
        # ...and only as a word of its own. Samsungas is the Lithuanian declension of
        # Samsung; without a boundary check the Estonian AS eats its ending and it
        # becomes a different string. Saab would lose its tail to AB the same way.
        ("Samsungas", "samsungas"),
        ("Saab", "saab"),
        # A brand actually called AS keeps its name.
        ("AS", "as"),
    ],
)
def test_normalization(raw, expected):
    assert normalize_brand(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "®", "..."])
def test_nothing_left_is_refused(raw):
    """A blank alias would match every offer whose brand field is a stray mark."""
    with pytest.raises(ValueError):
        normalize_brand(raw)


# --- brands ---


def test_two_brands_may_share_a_name(client):
    """Delta is taps and machine tools: two companies, not a duplicate."""
    token = admin_token(client)
    add_brand(client, token, "delta", "Delta")
    second = client.post(
        "/api/admin/brands",
        headers=auth(token),
        json={"slug": "delta-tools", "canonical_name": "Delta"},
    )
    assert second.status_code == 201


def test_the_slug_is_what_is_unique(client):
    token = admin_token(client)
    add_brand(client, token, "delta", "Delta")
    clash = client.post(
        "/api/admin/brands",
        headers=auth(token),
        json={"slug": "delta", "canonical_name": "Something else"},
    )
    assert clash.status_code == 409


def test_search_by_name(client):
    token = admin_token(client)
    add_brand(client, token, "samsung", "Samsung")
    add_brand(client, token, "sony", "Sony")
    found = client.get("/api/admin/brands?search=sams", headers=auth(token)).json()
    assert [b["slug"] for b in found["items"]] == ["samsung"]


# --- aliases ---


def test_spellings_collapse_to_one_row(client):
    token = admin_token(client)
    brand = add_brand(client, token, "samsung", "Samsung")

    assert add_alias(client, token, brand["id"], "Samsung®").status_code == 201
    # Same string once the noise is computed away — one alias, not two.
    assert add_alias(client, token, brand["id"], "  samsung ").status_code == 409

    aliases = client.get(f"/api/admin/brands/{brand['id']}/aliases", headers=auth(token)).json()
    assert [a["alias_normalized"] for a in aliases] == ["samsung"]
    assert aliases[0]["alias_raw"] == "Samsung®"


def test_a_declension_is_its_own_row(client):
    """No rule derives Samsungo from Samsung; Lithuanian grammar is not a typo."""
    token = admin_token(client)
    brand = add_brand(client, token, "samsung", "Samsung")
    for alias in ("Samsung", "Samsungo", "Samsungas", "Самсунг"):
        assert add_alias(client, token, brand["id"], alias).status_code == 201


def test_an_alias_that_normalizes_to_nothing(client):
    token = admin_token(client)
    brand = add_brand(client, token, "samsung", "Samsung")
    assert add_alias(client, token, brand["id"], "®").status_code == 422


def test_remove_an_alias(client):
    token = admin_token(client)
    brand = add_brand(client, token, "samsung", "Samsung")
    alias = add_alias(client, token, brand["id"], "Samsungo").json()

    dropped = client.delete(
        f"/api/admin/brands/{brand['id']}/aliases/{alias['id']}", headers=auth(token)
    )
    assert dropped.status_code == 204
    assert client.get(f"/api/admin/brands/{brand['id']}/aliases", headers=auth(token)).json() == []


def test_an_alias_of_another_brand_is_not_removable_here(client):
    token = admin_token(client)
    samsung = add_brand(client, token, "samsung", "Samsung")
    sony = add_brand(client, token, "sony", "Sony")
    alias = add_alias(client, token, sony["id"], "Sony").json()

    response = client.delete(
        f"/api/admin/brands/{samsung['id']}/aliases/{alias['id']}", headers=auth(token)
    )
    assert response.status_code == 404


# --- resolution, which is what the matcher will call ---


def test_one_result_is_a_deterministic_signal(client):
    token = admin_token(client)
    brand = add_brand(client, token, "samsung", "Samsung")
    add_alias(client, token, brand["id"], "Самсунг")

    found = client.get("/api/admin/brands/resolve?q=САМСУНГ", headers=auth(token)).json()
    assert len(found) == 1
    assert found[0]["brand"]["slug"] == "samsung"
    assert found[0]["matched_alias"] == "самсунг"


def test_two_results_mean_the_category_has_to_settle_it(client):
    token = admin_token(client)
    taps = add_brand(client, token, "delta", "Delta")
    tools = add_brand(client, token, "delta-tools", "Delta")
    for brand in (taps, tools):
        add_alias(client, token, brand["id"], "Delta")

    found = client.get("/api/admin/brands/resolve?q=delta", headers=auth(token)).json()
    assert {m["brand"]["slug"] for m in found} == {"delta", "delta-tools"}


def test_nothing_known_resolves_to_nothing(client):
    token = admin_token(client)
    assert client.get("/api/admin/brands/resolve?q=Nokla", headers=auth(token)).json() == []


def test_a_line_is_not_read_from_a_title(client):
    """ "Spigen case for iPhone 15" is not an Apple product."""
    token = admin_token(client)
    apple = add_brand(client, token, "apple", "Apple")
    add_alias(client, token, apple["id"], "Apple", kind="spelling")
    add_alias(client, token, apple["id"], "iPhone", kind="line")

    # A feed's brand field saying iPhone does mean Apple.
    from_field = client.get("/api/admin/brands/resolve?q=iPhone", headers=auth(token)).json()
    assert [m["brand"]["slug"] for m in from_field] == ["apple"]

    # Read out of a title, it must not.
    from_title = client.get(
        "/api/admin/brands/resolve?q=iPhone&titles_only=true", headers=auth(token)
    ).json()
    assert from_title == []

    # The spelling still resolves either way.
    assert (
        client.get(
            "/api/admin/brands/resolve?q=Apple&titles_only=true", headers=auth(token)
        ).json()[0]["brand"]["slug"]
        == "apple"
    )


# --- guards and the trail ---


def test_brands_require_an_admin_token(client):
    user_token = tokens(client, CUSTOMER)["access_token"]
    assert client.get("/api/admin/brands", headers=auth(user_token)).status_code == 401
    assert client.get("/api/admin/brands").status_code == 401


def test_adding_an_alias_is_recorded(client):
    token = admin_token(client)
    brand = add_brand(client, token, "samsung", "Samsung")
    add_alias(client, token, brand["id"], "Самсунг")

    entries = client.get(
        "/api/admin/audit", headers=auth(token), params={"path": "/aliases"}
    ).json()["items"]
    entry = next(e for e in entries if e["status_code"] == 201)
    assert entry["target_type"] == "brand"
    assert entry["target_id"] == str(brand["id"])
    assert entry["changes"] == {"added_alias": "самсунг", "kind": "spelling"}


# --- the model registry: what a maker calls what it makes ---


def a_category(client, token, slug="phones", name="Phones") -> int:
    made = client.post(
        "/api/admin/categories", headers=auth(token), json={"slug": slug, "name": name}
    )
    if made.status_code == 201:
        return made.json()["id"]
    listed = client.get("/api/admin/categories", headers=auth(token)).json()
    rows = listed["items"] if isinstance(listed, dict) else listed
    return next(row["id"] for row in rows if row["slug"] == slug)


def add_model(client, token, brand_id, alias, model, category_id=None, **extra):
    return client.post(
        f"/api/admin/brands/{brand_id}/models",
        headers=auth(token),
        json={
            "alias": alias,
            "model": model,
            "category_id": category_id or a_category(client, token),
            **extra,
        },
    )


def test_a_model_name_is_stored_as_words_and_once(client):
    token = admin_token(client)
    brand = add_brand(client, token, "samsung", "Samsung")

    created = add_model(client, token, brand["id"], "Galaxy  S26 5G", "Galaxy S26")
    assert created.status_code == 201, created.text
    assert created.json()["alias_normalized"] == "galaxy s26 5g"
    assert created.json()["model"] == "Galaxy S26"
    # The same words once case and spacing are computed away — one row, not two.
    assert add_model(client, token, brand["id"], "galaxy s26 5g", "Galaxy S26").status_code == 409

    # `+` survives: it is the one mark that tells two models apart.
    plus = add_model(client, token, brand["id"], "Galaxy S26+", "Galaxy S26+")
    assert plus.status_code == 201
    assert plus.json()["alias_normalized"] == "galaxy s26+"

    listed = client.get(f"/api/admin/brands/{brand['id']}/models", headers=auth(token)).json()
    assert [(row["alias_normalized"], row["model"]) for row in listed] == [
        ("galaxy s26 5g", "Galaxy S26"),
        ("galaxy s26+", "Galaxy S26+"),
    ]


def test_a_spec_sheet_is_not_a_model_name(client):
    """The reader looks up windows of at most six words; a longer alias would sit in the
    table and match nothing, so it is refused rather than stored."""
    token = admin_token(client)
    brand = add_brand(client, token, "motorola", "Motorola")
    refused = add_model(
        client,
        token,
        brand["id"],
        "Motorola razr fold 20.6 cm Dual SIM Android 16.0 5G USB Type-C",
        "razr fold",
    )
    assert refused.status_code == 422
    assert add_model(client, token, brand["id"], "(+)", "x").status_code == 422


def test_remove_a_model_name_and_only_from_its_own_brand(client):
    token = admin_token(client)
    samsung = add_brand(client, token, "samsung", "Samsung")
    apple = add_brand(client, token, "apple", "Apple")
    row = add_model(client, token, samsung["id"], "Galaxy S26", "Galaxy S26").json()

    wrong_brand = client.delete(
        f"/api/admin/brands/{apple['id']}/models/{row['id']}", headers=auth(token)
    )
    assert wrong_brand.status_code == 404

    removed = client.delete(
        f"/api/admin/brands/{samsung['id']}/models/{row['id']}", headers=auth(token)
    )
    assert removed.status_code == 204
    assert client.get(f"/api/admin/brands/{samsung['id']}/models", headers=auth(token)).json() == []


def test_adding_a_model_name_is_recorded(client):
    token = admin_token(client)
    brand = add_brand(client, token, "samsung", "Samsung")
    add_model(client, token, brand["id"], "S26", "Galaxy S26")

    entries = client.get(
        "/api/admin/audit", headers=auth(token), params={"path": "/models"}
    ).json()["items"]
    entry = next(e for e in entries if e["status_code"] == 201)
    assert entry["target_type"] == "brand"
    assert entry["target_id"] == str(brand["id"])
    assert entry["changes"] == {
        "added_model_alias": "s26",
        "model": "Galaxy S26",
        "category_id": a_category(client, token),
    }


def test_a_model_name_belongs_to_one_kind_of_product(client):
    """Nubia's phone `Air` was found whole in `Apple iPad Air`: a maker's names for its
    phones are not its names for its tablets, and each category reads its own."""
    token = admin_token(client)
    brand = add_brand(client, token, "apple", "Apple")
    phones = a_category(client, token)
    tablets = a_category(client, token, "tablets", "Tablets")

    assert add_model(client, token, brand["id"], "Air", "iPhone Air", phones).status_code == 201
    # The same spelling is another model in another category, not a conflict.
    assert add_model(client, token, brand["id"], "Air", "iPad Air", tablets).status_code == 201
    assert add_model(client, token, brand["id"], "air", "iPad Air", tablets).status_code == 409

    only = client.get(
        f"/api/admin/brands/{brand['id']}/models",
        headers=auth(token),
        params={"category_id": tablets},
    ).json()
    assert [(row["model"], row["category_id"]) for row in only] == [("iPad Air", tablets)]
    assert add_model(client, token, brand["id"], "X", "X", 999999).status_code == 404


def test_a_listing_reads_only_its_own_category_s_names(client):
    """The registry read a phone's name into a tablet's title when it was keyed by brand
    alone. A phones channel reads the phones page, and a name entered for tablets is not on
    it."""
    from tests.test_matching import a_shop_we_can_build_from
    from tests.test_offers import ingest

    token = admin_token(client)
    _, source, phones, apple = a_shop_we_can_build_from(client, token)
    tablets = a_category(client, token, "tablets", "Tablets")
    add_model(client, token, apple["id"], "Pixel Air", "Pixel Air", tablets)

    def model() -> str:
        result = ingest(
            client,
            token,
            source["id"],
            {
                "external_id": "X-1",
                "market_code": "LV",
                "payload": {
                    "name": "Apple Pixel Air 128GB black",
                    "brand": "Apple",
                    "model": "as read",
                },
            },
        )
        reading = client.post(
            f"/api/admin/raw-offers/{result['raw_offer_id']}/renormalize", headers=auth(token)
        )
        return reading.json()["model"]

    assert model() == "as read", "a tablet's name was read into a phone"
    add_model(client, token, apple["id"], "Pixel Air", "Pixel Air", phones["id"])
    assert model() == "Pixel Air"


def test_a_renamed_brand_retitles_what_it_makes(client):
    """`CAT` became `Cat`, and every entry went on reading `CAT S75` until something else
    happened to touch it: a title carries the maker's name."""
    from tests.test_matching import (
        a_shop_we_can_build_from,
        a_storage_axis,
        admin_token,
        offer_from,
        promote,
    )

    token = admin_token(client)
    _, source, category, apple = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])
    variant_id = promote(
        client,
        token,
        offer_from(
            client,
            token,
            source["id"],
            {
                "name": "Apple iPhone 17 256GB",
                "brand": "Apple",
                "model": "iPhone 17",
                "attributes": {"storage": "256 GB"},
            },
        ),
    )["variant_id"]
    renamed = client.patch(
        f"/api/admin/brands/{apple['id']}", headers=auth(token), json={"canonical_name": "APPLE"}
    )
    assert renamed.status_code == 200, renamed.text
    entry = client.get(f"/api/admin/variants/{variant_id}", headers=auth(token)).json()
    assert entry["title"].startswith("APPLE iPhone 17"), entry["title"]
    family = client.get(f"/api/admin/products/{entry['product']['id']}", headers=auth(token)).json()
    assert family["title"] == "APPLE iPhone 17"
