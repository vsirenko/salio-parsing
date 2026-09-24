"""The admin's list of families: sorted, filtered, searched, and readable without lookups."""

from tests.test_auth import auth
from tests.test_catalog import admin_token, phones_setup, post


def families(client, token):
    """Three families of two brands, one of them hidden, one with a barcode and a part number."""
    apple, phones, *_ = phones_setup(client, token)
    samsung = post(
        client, token, "/api/admin/brands", {"slug": "samsung", "canonical_name": "Samsung"}
    )
    made = {}
    for brand, model in ((apple, "iPhone 15"), (apple, "iPhone 16"), (samsung, "Galaxy S26")):
        made[model] = post(
            client,
            token,
            "/api/admin/products",
            {"brand_id": brand["id"], "category_id": phones["id"], "model": model},
        )
    client.patch(
        f"/api/admin/products/{made['Galaxy S26']['id']}",
        headers=auth(token),
        json={"is_visible": False},
    )
    variant = post(
        client,
        token,
        "/api/admin/variants",
        {
            "brand_id": apple["id"],
            "category_id": phones["id"],
            "model": "iPhone 16",
            "product_id": made["iPhone 16"]["id"],
        },
    )
    post(client, token, f"/api/admin/variants/{variant['id']}/gtins", {"value": "4006381333931"})
    post(client, token, f"/api/admin/variants/{variant['id']}/mpns", {"value": "MRXN3ZD/A"})
    return apple, samsung, phones, made


def listed(client, token, **params) -> list[str]:
    response = client.get("/api/admin/products", headers=auth(token), params=params)
    assert response.status_code == 200, response.text
    return [row["model"] for row in response.json()["items"]]


def test_a_row_names_its_brand_and_category_and_says_whether_it_is_comparable(client):
    token = admin_token(client)
    apple, _, phones, made = families(client, token)
    row = client.get(f"/api/admin/products/{made['iPhone 16']['id']}", headers=auth(token)).json()
    assert row["brand"] == {"id": apple["id"], "canonical_name": "Apple"}
    assert row["category"] == {"id": phones["id"], "name": phones["name"]}
    assert (row["variants_count"], row["shops_count"], row["min_price"]) == (1, 0, None)


def test_sorting_is_by_the_keys_allowed_and_an_unknown_one_is_refused(client):
    token = admin_token(client)
    families(client, token)
    assert listed(client, token) == ["iPhone 15", "iPhone 16", "Galaxy S26"]
    # Titles are brand and model: `Samsung Galaxy S26`, `Apple iPhone 16`, `Apple iPhone 15`.
    assert listed(client, token, sort="-title") == ["Galaxy S26", "iPhone 16", "iPhone 15"]
    # Two Apples tie on the brand, and the id breaks the tie.
    assert listed(client, token, sort="-brand") == ["Galaxy S26", "iPhone 15", "iPhone 16"]
    refused = client.get("/api/admin/products", headers=auth(token), params={"sort": "price"})
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "unknown_sort_key"
    assert "min_price" in refused.json()["error"]["details"]["allowed"]


def test_several_brands_visibility_and_a_creation_window(client):
    token = admin_token(client)
    apple, samsung, *_ = families(client, token)
    both = listed(client, token, brand_id=[apple["id"], samsung["id"]])
    assert sorted(both) == ["Galaxy S26", "iPhone 15", "iPhone 16"]
    assert listed(client, token, brand_id=[samsung["id"]]) == ["Galaxy S26"]
    assert listed(client, token, is_visible="false") == ["Galaxy S26"]
    assert listed(client, token, created_to="2000-01-01T00:00:00Z") == []


def test_search_finds_a_family_by_its_id_barcode_part_number_or_words(client):
    token = admin_token(client)
    *_, made = families(client, token)
    # A short number is looked for as an id and in the words alike.
    assert "iPhone 15" in listed(client, token, search=str(made["iPhone 15"]["id"]))
    # The barcode as printed on a box, without the padding it is stored with.
    assert listed(client, token, search="4006381333931") == ["iPhone 16"]
    assert listed(client, token, search="mrxn3zd/a") == ["iPhone 16"]
    assert listed(client, token, search="galaxy") == ["Galaxy S26"]


def test_brands_can_be_asked_for_by_id(client):
    token = admin_token(client)
    apple, samsung, *_ = families(client, token)
    response = client.get("/api/admin/brands", headers=auth(token), params={"ids": [samsung["id"]]})
    assert [b["canonical_name"] for b in response.json()["items"]] == ["Samsung"]
