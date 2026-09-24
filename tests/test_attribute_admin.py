"""The attribute registry as an admin keeps it: counts, edits, lookups, labels, removals."""

from tests.test_auth import auth
from tests.test_catalog import admin_token, post
from tests.test_offer_list import an_entry_with_listings


def colour(client, token):
    attribute = post(
        client,
        token,
        "/api/admin/attributes",
        {"key": "colour", "name": "Colour", "value_type": "enum"},
    )
    black = post(
        client, token, f"/api/admin/attributes/{attribute['id']}/values", {"canonical": "black"}
    )
    white = post(
        client, token, f"/api/admin/attributes/{attribute['id']}/values", {"canonical": "white"}
    )
    melns = post(
        client,
        token,
        f"/api/admin/attributes/values/{black['id']}/aliases",
        {"alias": "Melns", "language": "lv"},
    )
    krasa = post(
        client,
        token,
        f"/api/admin/attributes/{attribute['id']}/aliases",
        {"alias": "Krāsa", "language": "lv"},
    )
    return attribute, black, white, melns, krasa


def test_a_row_counts_where_an_attribute_is_used_and_sorts_and_searches(client):
    token = admin_token(client)
    an_entry_with_listings(client, token)
    attribute, *_ = colour(client, token)
    rows = client.get(
        "/api/admin/attributes", headers=auth(token), params={"sort": "-variants_count"}
    ).json()["items"]
    storage = rows[0]
    assert storage["key"] == "storage_mb"
    assert (storage["categories_count"], storage["variants_count"]) == (1, 1)
    by_key = {row["key"]: row for row in rows}
    assert (by_key["colour"]["values_count"], by_key["colour"]["aliases_count"]) == (2, 1)
    # A name a shop gives it finds it.
    found = client.get("/api/admin/attributes", headers=auth(token), params={"search": "krāsa"})
    assert [row["key"] for row in found.json()["items"]] == ["colour"]
    assert (
        client.get(
            "/api/admin/attributes", headers=auth(token), params={"sort": "size"}
        ).status_code
        == 422
    )


def test_the_name_and_labels_change_and_a_stored_unit_does_not(client):
    token = admin_token(client)
    an_entry_with_listings(client, token)
    storage = client.get(
        "/api/admin/attributes", headers=auth(token), params={"search": "storage_mb"}
    ).json()["items"][0]
    renamed = client.patch(
        f"/api/admin/attributes/{storage['id']}",
        headers=auth(token),
        json={"name": "Built-in storage", "labels": {"LV": "Iekšējā atmiņa", "ru": " "}},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["labels"] == {"lv": "Iekšējā atmiņa"}
    refused = client.patch(
        f"/api/admin/attributes/{storage['id']}", headers=auth(token), json={"unit_dimension": "GB"}
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "values_stored"
    bad = client.patch(
        f"/api/admin/attributes/{storage['id']}",
        headers=auth(token),
        json={"labels": {"latvian": "x"}},
    )
    assert bad.status_code == 422


def test_an_attribute_says_where_it_is_bound_and_what_a_string_resolves_to(client):
    token = admin_token(client)
    _, variant_id, *_ = an_entry_with_listings(client, token)
    attribute, black, _, melns, _ = colour(client, token)
    category = client.get(f"/api/admin/variants/{variant_id}", headers=auth(token)).json()[
        "category"
    ]
    post(
        client,
        token,
        f"/api/admin/categories/{category['id']}/attributes",
        {
            "attribute_id": attribute["id"],
            "identity_bearing": True,
            "position": 2,
            "label_override": "Krāsa",
        },
    )
    bound = client.get(
        f"/api/admin/attributes/{attribute['id']}/categories", headers=auth(token)
    ).json()
    assert [(b["category_id"], b["identity_bearing"], b["label_override"]) for b in bound] == [
        (category["id"], True, "Krāsa")
    ]

    def resolve(q):
        return client.get(
            f"/api/admin/attributes/{attribute['id']}/resolve", headers=auth(token), params={"q": q}
        ).json()

    assert (resolve("MELNS")["value"]["canonical"], resolve("MELNS")["via"]) == ("black", "alias")
    assert resolve("Black")["via"] == "canonical"
    assert resolve("krāsa:")["is_attribute_name"] is True
    assert resolve("zaļš")["value"] is None


def test_values_carry_their_aliases_and_are_removed_only_when_nothing_carries_them(client):
    token = admin_token(client)
    attribute, black, white, melns, krasa = colour(client, token)
    values = client.get(
        f"/api/admin/attributes/{attribute['id']}/values", headers=auth(token)
    ).json()
    first = next(v for v in values if v["canonical"] == "black")
    assert [a["alias_normalized"] for a in first["aliases"]] == ["melns"]
    assert first["variants_count"] == 0

    relabelled = client.patch(
        f"/api/admin/attributes/values/{black['id']}",
        headers=auth(token),
        json={"position": 3, "labels": {"ru": "чёрный"}},
    ).json()
    assert (relabelled["position"], relabelled["labels"]) == (3, {"ru": "чёрный"})
    assert (
        client.patch(
            f"/api/admin/attributes/values/{black['id']}",
            headers=auth(token),
            json={"canonical": "noir"},
        ).status_code
        == 422
    ), "the canonical string is not renamed"

    assert (
        client.delete(
            f"/api/admin/attributes/values/{white['id']}/aliases/{melns['id']}", headers=auth(token)
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/admin/attributes/values/{black['id']}/aliases/{melns['id']}", headers=auth(token)
        ).status_code
        == 204
    )
    assert (
        client.delete(
            f"/api/admin/attributes/{attribute['id']}/aliases/{krasa['id']}", headers=auth(token)
        ).status_code
        == 204
    )
    assert (
        client.delete(
            f"/api/admin/attributes/values/{white['id']}", headers=auth(token)
        ).status_code
        == 204
    )


def test_a_value_an_entry_carries_is_not_removed(client):
    token = admin_token(client)
    _, variant_id, *_ = an_entry_with_listings(client, token)
    a = post(
        client,
        token,
        "/api/admin/attributes",
        {"key": "finish", "name": "Finish", "value_type": "enum"},
    )
    matte = post(client, token, f"/api/admin/attributes/{a['id']}/values", {"canonical": "matte"})
    category = client.get(f"/api/admin/variants/{variant_id}", headers=auth(token)).json()[
        "category"
    ]
    post(
        client,
        token,
        f"/api/admin/categories/{category['id']}/attributes",
        {"attribute_id": a["id"]},
    )
    client.put(
        f"/api/admin/variants/{variant_id}/attributes",
        headers=auth(token),
        json={"attribute_id": a["id"], "value_id": matte["id"]},
    )
    refused = client.delete(f"/api/admin/attributes/values/{matte['id']}", headers=auth(token))
    assert refused.status_code == 409
    assert refused.json()["error"]["details"]["variants_count"] == 1
