"""What looks filed twice: a queue with the evidence beside each item, and nothing changed."""

from tests.test_auth import auth
from tests.test_catalog import admin_token, post
from tests.test_matching import a_colour_axis, a_shop_we_can_build_from, a_storage_axis


def suspects(client, token, **params):
    response = client.get("/api/admin/matching/suspects", headers=auth(token), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def setup(client, token):
    _, _, category, brand = a_shop_we_can_build_from(client, token)
    storage = a_storage_axis(client, token, category["id"])
    colour = a_colour_axis(client, token, category["id"])
    values = {
        value["canonical"]: value["id"]
        for value in client.get(
            f"/api/admin/attributes/{colour['id']}/values", headers=auth(token)
        ).json()
    }
    return category, brand, storage, colour, values


def entry(client, token, category, brand, model, axes, mpn=None):
    variant = post(
        client,
        token,
        "/api/admin/variants",
        {"brand_id": brand["id"], "category_id": category["id"], "model": model},
    )
    for body in axes:
        response = client.put(
            f"/api/admin/variants/{variant['id']}/attributes", headers=auth(token), json=body
        )
        assert response.status_code == 200, response.text
    if mpn:
        post(client, token, f"/api/admin/variants/{variant['id']}/mpns", {"value": mpn})
    return variant["id"]


def test_one_part_number_on_entries_that_agree_is_a_merge_to_make(client):
    token = admin_token(client)
    category, brand, storage, colour, values = setup(client, token)
    same = [
        {"attribute_id": storage["id"], "value_num": "262144"},
        {"attribute_id": colour["id"], "value_id": values["black"]},
    ]
    one = entry(client, token, category, brand, "MacBook Air", same, "MDH74ZE/A")
    two = entry(client, token, category, brand, "Apple MacBook Air", same, "mdh74ze/a")
    # A number shared by entries that differ is a family's number, not one product twice.
    entry(client, token, category, brand, "Galaxy S26", same, "SM-S948B")
    blue = [same[0], {"attribute_id": colour["id"], "value_id": values["blue"]}]
    entry(client, token, category, brand, "Galaxy S26 blue", blue, "SM-S948B")

    [found] = suspects(client, token, kind="part_number")["items"]
    assert (found["action"], found["evidence"]) == ("merge", "MDH74ZE/A")
    assert {e["id"] for e in found["entries"]} == {one, two}


def test_one_model_at_two_nearly_equal_numbers_is_a_reading_to_fix(client):
    """`1000 GB` and `1 TB` are 1024000 and 1048576 MB: one disk read two ways."""
    token = admin_token(client)
    category, brand, storage, colour, values = setup(client, token)
    black = {"attribute_id": colour["id"], "value_id": values["black"]}
    entry(
        client,
        token,
        category,
        brand,
        "MacBook Air",
        [{"attribute_id": storage["id"], "value_num": "1048576"}, black],
    )
    entry(
        client,
        token,
        category,
        brand,
        "MacBook Air",
        [{"attribute_id": storage["id"], "value_num": "1024000"}, black],
    )
    # Two capacities really are two products.
    entry(
        client,
        token,
        category,
        brand,
        "MacBook Air",
        [{"attribute_id": storage["id"], "value_num": "524288"}, black],
    )

    [found] = suspects(client, token, kind="near_value")["items"]
    assert (found["action"], found["evidence"]) == ("axis", "storage_mb")
    assert "1024000 and 1048576" in found["detail"] or "1048576 and 1024000" in found["detail"]


def test_one_name_in_another_word_order_is_an_alias_to_enter(client):
    token = admin_token(client)
    category, brand, *_ = setup(client, token)
    for model in ("16 Plus", "Plus 16", "16 PLUS", "Pro 16"):
        post(
            client,
            token,
            "/api/admin/products",
            {"brand_id": brand["id"], "category_id": category["id"], "model": model},
        )
    [found] = suspects(client, token, kind="word_order")["items"]
    assert found["action"] == "registry"
    assert sorted(e["model"] for e in found["entries"]) == ["16 PLUS", "16 Plus", "Plus 16"]


def test_the_report_changes_nothing_and_filters(client):
    token = admin_token(client)
    category, brand, *_ = setup(client, token)
    for model in ("16 Plus", "Plus 16"):
        post(
            client,
            token,
            "/api/admin/products",
            {"brand_id": brand["id"], "category_id": category["id"], "model": model},
        )
    assert suspects(client, token)["by_kind"] == {"word_order": 1}
    assert suspects(client, token, category_id=999999)["total"] == 0
    assert suspects(client, token)["total"] == 1
