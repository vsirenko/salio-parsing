"""The catalogue: families, variants, and the three values derived from them."""

from decimal import Decimal

from app.features.catalog.identity import compute_identity_key, normalize_model, slugify
from tests.test_auth import ADMIN, CUSTOMER, auth, tokens


def admin_token(client) -> str:
    return tokens(client, ADMIN, panel="/admin")["access_token"]


def post(client, token, path, body, expect=201):
    response = client.post(path, headers=auth(token), json=body)
    assert response.status_code == expect, response.text
    return response.json()


def phones_setup(client, token):
    """A brand, a category, and two identity-bearing attributes on it."""
    brand = post(client, token, "/api/admin/brands", {"slug": "apple", "canonical_name": "Apple"})
    category = post(
        client, token, "/api/admin/categories", {"slug": "smartphones", "name": "Smartphones"}
    )
    capacity = post(
        client,
        token,
        "/api/admin/attributes",
        {
            "key": "capacity",
            "name": "Capacity",
            "value_type": "number",
            "unit_dimension": "bytes",
            "scale": 0,
        },
    )
    color = post(
        client,
        token,
        "/api/admin/attributes",
        {"key": "color", "name": "Colour", "value_type": "enum"},
    )
    black = post(
        client, token, f"/api/admin/attributes/{color['id']}/values", {"canonical": "black"}
    )
    for attribute, position in ((capacity, 1), (color, 2)):
        post(
            client,
            token,
            f"/api/admin/categories/{category['id']}/attributes",
            {"attribute_id": attribute["id"], "identity_bearing": True, "position": position},
        )
    return brand, category, capacity, color, black


# --- the derivation, on its own ---


def test_model_normalization_is_language_neutral():
    forms = ["WW90T554DAX", "ww90t554-dax", "WW 90 T554 DAX"]
    assert len({normalize_model(f) for f in forms}) == 1


def test_a_slug_carries_its_id():
    assert slugify("iPhone 15 Pro 256GB Natural Titanium", entity_id=14237).endswith("-14237")
    # Diacritics survive as their ASCII shape rather than disappearing.
    assert slugify("Rīgas Elektronika", entity_id=7) == "rigas-elektronika-7"


def test_the_key_ignores_order_and_decimal_shape():
    common = dict(
        brand_id=1, category_id=2, model_normalized="iphone15pro", kind="single", unit_count=1
    )
    axes = {"capacity", "color"}
    first = compute_identity_key(
        **common, identity_values={"capacity": Decimal("256"), "color": "black"}, expected_keys=axes
    )
    second = compute_identity_key(
        **common,
        identity_values={"color": "black", "capacity": Decimal("256.00")},
        expected_keys=axes,
    )
    assert first == second


def test_the_key_separates_categories():
    common = dict(model_normalized="x", kind="single", unit_count=1)
    values = {"capacity": Decimal("256")}
    phone = compute_identity_key(
        **common, brand_id=1, category_id=2, identity_values=values, expected_keys={"capacity"}
    )
    tablet = compute_identity_key(
        **common, brand_id=1, category_id=3, identity_values=values, expected_keys={"capacity"}
    )
    assert phone != tablet


# --- products ---


def test_a_product_title_is_generated(client):
    token = admin_token(client)
    brand, category, *_ = phones_setup(client, token)
    product = post(
        client,
        token,
        "/api/admin/products",
        {"brand_id": brand["id"], "category_id": category["id"], "model": "iPhone 15 Pro"},
    )
    assert product["title"] == "Apple iPhone 15 Pro"
    assert product["slug"] == f"apple-iphone-15-pro-{product['id']}"


def test_neither_title_nor_slug_is_writable(client):
    token = admin_token(client)
    brand, category, *_ = phones_setup(client, token)
    product = post(
        client,
        token,
        "/api/admin/products",
        {"brand_id": brand["id"], "category_id": category["id"], "model": "iPhone 15 Pro"},
    )
    for body in ({"title": "Whatever"}, {"slug": "whatever"}):
        response = client.patch(
            f"/api/admin/products/{product['id']}", headers=auth(token), json=body
        )
        assert response.status_code == 422


def test_an_override_survives_regeneration(client):
    token = admin_token(client)
    brand, category, *_ = phones_setup(client, token)
    product = post(
        client,
        token,
        "/api/admin/products",
        {"brand_id": brand["id"], "category_id": category["id"], "model": "iPhone 15 Pro"},
    )
    client.patch(
        f"/api/admin/products/{product['id']}",
        headers=auth(token),
        json={"title_override": "The good phone"},
    )
    renamed = client.patch(
        f"/api/admin/products/{product['id']}",
        headers=auth(token),
        json={"model": "iPhone 15 Pro Max"},
    ).json()

    assert renamed["title"] == "Apple iPhone 15 Pro Max"
    assert renamed["title_override"] == "The good phone"


# --- variants and the identity key ---


def test_the_key_appears_only_when_every_axis_is_filled(client):
    token = admin_token(client)
    brand, category, capacity, color, black = phones_setup(client, token)
    variant = post(
        client,
        token,
        "/api/admin/variants",
        {"brand_id": brand["id"], "category_id": category["id"], "model": "iPhone 15 Pro"},
    )
    assert variant["identity_key"] is None

    # One of two axes: still not enough.
    client.put(
        f"/api/admin/variants/{variant['id']}/attributes",
        headers=auth(token),
        json={"attribute_id": capacity["id"], "value_num": "256"},
    )
    assert (
        client.get(f"/api/admin/variants/{variant['id']}", headers=auth(token)).json()[
            "identity_key"
        ]
        is None
    )

    # The second one completes it.
    client.put(
        f"/api/admin/variants/{variant['id']}/attributes",
        headers=auth(token),
        json={"attribute_id": color["id"], "value_id": black["id"]},
    )
    full = client.get(f"/api/admin/variants/{variant['id']}", headers=auth(token)).json()
    assert full["identity_key"] is not None
    assert full["title"] == "Apple iPhone 15 Pro 256 black"


def test_clearing_an_axis_takes_the_key_away(client):
    token = admin_token(client)
    brand, category, capacity, color, black = phones_setup(client, token)
    variant = post(
        client,
        token,
        "/api/admin/variants",
        {"brand_id": brand["id"], "category_id": category["id"], "model": "iPhone 15 Pro"},
    )
    for body in (
        {"attribute_id": capacity["id"], "value_num": "256"},
        {"attribute_id": color["id"], "value_id": black["id"]},
    ):
        client.put(
            f"/api/admin/variants/{variant['id']}/attributes", headers=auth(token), json=body
        )

    dropped = client.delete(
        f"/api/admin/variants/{variant['id']}/attributes/{color['id']}", headers=auth(token)
    )
    assert dropped.status_code == 204
    assert (
        client.get(f"/api/admin/variants/{variant['id']}", headers=auth(token)).json()[
            "identity_key"
        ]
        is None
    )


def test_two_variants_of_the_same_thing_collide_on_the_key(client):
    """Which is the point: the second one cannot be created twice over."""
    token = admin_token(client)
    brand, category, capacity, color, black = phones_setup(client, token)
    body = {"brand_id": brand["id"], "category_id": category["id"], "model": "iPhone 15 Pro"}
    first = post(client, token, "/api/admin/variants", body)
    second = post(client, token, "/api/admin/variants", body)

    for variant in (first, second):
        client.put(
            f"/api/admin/variants/{variant['id']}/attributes",
            headers=auth(token),
            json={"attribute_id": capacity["id"], "value_num": "256"},
        )

    filled = client.put(
        f"/api/admin/variants/{first['id']}/attributes",
        headers=auth(token),
        json={"attribute_id": color["id"], "value_id": black["id"]},
    )
    assert filled.status_code == 200

    clash = client.put(
        f"/api/admin/variants/{second['id']}/attributes",
        headers=auth(token),
        json={"attribute_id": color["id"], "value_id": black["id"]},
    )
    assert clash.status_code == 409
    error = clash.json()["error"]
    assert error["code"] == "identity_taken"
    # It says which row to merge into rather than just refusing.
    assert error["details"]["variant_id"] == first["id"]


def test_identified_filter(client):
    token = admin_token(client)
    brand, category, capacity, color, black = phones_setup(client, token)
    plain = post(
        client,
        token,
        "/api/admin/variants",
        {"brand_id": brand["id"], "category_id": category["id"], "model": "iPhone 15"},
    )
    assert plain["identity_key"] is None

    without = client.get("/api/admin/variants?identified=false", headers=auth(token)).json()
    assert without["total"] == 1


def test_a_value_has_to_match_the_attribute_type(client):
    token = admin_token(client)
    brand, category, capacity, color, black = phones_setup(client, token)
    variant = post(
        client,
        token,
        "/api/admin/variants",
        {"brand_id": brand["id"], "category_id": category["id"], "model": "iPhone 15 Pro"},
    )
    # capacity is a number; an enum id is not a value for it.
    wrong = client.put(
        f"/api/admin/variants/{variant['id']}/attributes",
        headers=auth(token),
        json={"attribute_id": capacity["id"], "value_id": black["id"]},
    )
    assert wrong.status_code == 422
    assert wrong.json()["error"]["code"] == "value_type_mismatch"

    # ...and an enum value belonging to another attribute is refused by name.
    stray = client.put(
        f"/api/admin/variants/{variant['id']}/attributes",
        headers=auth(token),
        json={"attribute_id": color["id"], "value_id": 999},
    )
    assert stray.status_code == 422


def test_a_variant_may_have_no_family(client):
    token = admin_token(client)
    brand, category, *_ = phones_setup(client, token)
    variant = post(
        client,
        token,
        "/api/admin/variants",
        {"brand_id": brand["id"], "category_id": category["id"], "model": "iPhone 15 Pro"},
    )
    assert variant["product_id"] is None

    product = post(
        client,
        token,
        "/api/admin/products",
        {"brand_id": brand["id"], "category_id": category["id"], "model": "iPhone 15 Pro"},
    )
    grouped = client.patch(
        f"/api/admin/variants/{variant['id']}",
        headers=auth(token),
        json={"product_id": product["id"]},
    ).json()
    assert grouped["product_id"] == product["id"]


def test_unit_count_only_goes_with_a_multipack(client):
    token = admin_token(client)
    brand, category, *_ = phones_setup(client, token)
    base = {"brand_id": brand["id"], "category_id": category["id"], "model": "Cable"}

    pack = {**base, "kind": "multipack", "unit_count": 6}
    assert post(client, token, "/api/admin/variants", pack)
    for bad in ({"kind": "single", "unit_count": 6}, {"kind": "multipack", "unit_count": 1}):
        response = client.post("/api/admin/variants", headers=auth(token), json={**base, **bad})
        assert response.status_code == 422


# --- barcodes and part numbers ---


def test_a_variant_has_more_than_one_barcode(client):
    token = admin_token(client)
    brand, category, *_ = phones_setup(client, token)
    variant = post(
        client,
        token,
        "/api/admin/variants",
        {"brand_id": brand["id"], "category_id": category["id"], "model": "iPhone 15 Pro"},
    )
    for gtin in ("194253000001", "0194253000002"):
        post(client, token, f"/api/admin/variants/{variant['id']}/gtins", {"value": gtin})

    listed = client.get(f"/api/admin/variants/{variant['id']}/gtins", headers=auth(token)).json()
    assert len(listed) == 2

    assert (
        client.post(
            f"/api/admin/variants/{variant['id']}/gtins",
            headers=auth(token),
            json={"value": "not-a-barcode"},
        ).status_code
        == 409
    )


def test_a_part_number_is_stored_beside_its_brand(client):
    token = admin_token(client)
    brand, category, *_ = phones_setup(client, token)
    variant = post(
        client,
        token,
        "/api/admin/variants",
        {"brand_id": brand["id"], "category_id": category["id"], "model": "iPhone 15 Pro"},
    )
    mpn = post(client, token, f"/api/admin/variants/{variant['id']}/mpns", {"value": "MRXN3ZD/A"})
    assert mpn["brand_id"] == brand["id"]
    assert mpn["mpn_normalized"] == "mrxn3zda"
    assert mpn["mpn_raw"] == "MRXN3ZD/A"


# --- guards ---


def test_the_catalogue_requires_an_admin_token(client):
    user_token = tokens(client, CUSTOMER)["access_token"]
    assert client.get("/api/admin/variants", headers=auth(user_token)).status_code == 401
    assert client.get("/api/admin/products").status_code == 401
