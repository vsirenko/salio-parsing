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
    for model in ("16 Plus", "Plus 16", "16 PLUS", "Pro 16", "Galaxy S25", "Galaxy S25+"):
        post(
            client,
            token,
            "/api/admin/products",
            {"brand_id": brand["id"], "category_id": category["id"], "model": model},
        )
    # A plus is a word: `Galaxy S25+` is another phone, not another spelling.
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


def test_a_size_read_as_a_name_is_a_reading_to_fix_and_not_an_alias(client):
    token = admin_token(client)
    category, brand, *_ = setup(client, token)
    for model in ("15.6", '15.6"'):
        post(
            client,
            token,
            "/api/admin/products",
            {"brand_id": brand["id"], "category_id": category["id"], "model": model},
        )
    body = suspects(client, token)
    assert body["by_kind"] == {"not_a_name": 2}
    item = body["items"][0]
    assert item["action"] == "reading"
    # The ids the fix is made with: the registry and a reparse are keyed by them.
    assert item["brand"] == {"id": brand["id"], "name": "Apple"}
    assert item["category"]["id"] == category["id"]


def test_a_part_number_with_a_space_in_it_is_not_a_code(client):
    """`Galaxy S25 256-Silverblue` is a piece of a title a shop put in the field."""
    token = admin_token(client)
    category, brand, storage, colour, values = setup(client, token)
    same = [{"attribute_id": storage["id"], "value_num": "12288"}]
    entry(client, token, category, brand, "Galaxy S25 Ultra", same, "Galaxy S25 256-Silverblue")
    entry(client, token, category, brand, "Galaxy | S25 Ultra", same, "Galaxy S25 256-Silverblue")
    assert suspects(client, token, kind="part_number")["items"] == []


def test_a_chosen_pair_is_merged_and_one_that_differs_is_refused_unless_said(client):
    token = admin_token(client)
    category, brand, storage, colour, values = setup(client, token)
    black = {"attribute_id": colour["id"], "value_id": values["black"]}
    blue = {"attribute_id": colour["id"], "value_id": values["blue"]}
    size = {"attribute_id": storage["id"], "value_num": "262144"}
    one = entry(client, token, category, brand, "MacBook Air", [size, black])
    two = entry(client, token, category, brand, "Apple MacBook Air", [size, black])
    other = entry(client, token, category, brand, "MacBook Air M5", [size, blue])

    def merge(from_id, into_id, **extra):
        return client.post(
            "/api/admin/matching/merge/pair",
            headers=auth(token),
            json={"from_id": from_id, "into_id": into_id, **extra},
        )

    done = merge(two, one, reason="one MacBook written twice")
    assert done.status_code == 200, done.text
    assert (done.json()["from"]["id"], done.json()["into"]["id"]) == (two, one)
    assert client.get(f"/api/admin/variants/{two}", headers=auth(token)).status_code == 404

    refused = merge(other, one)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "axes_differ"
    assert refused.json()["error"]["details"]["axes"][0]["key"] == "color"
    forced = merge(other, one, despite_axes=True)
    assert forced.status_code == 200, forced.text
    kept = client.get(f"/api/admin/variants/{one}", headers=auth(token)).json()
    assert kept["axes"]["color"] == "black"
    assert merge(one, one).status_code == 422
    assert merge(999999, one).status_code == 404
