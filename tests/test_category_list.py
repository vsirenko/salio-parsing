"""Categories as a tree page and a filter use them, and an entry's attributes as shown."""

from tests.test_auth import auth
from tests.test_catalog import admin_token, post
from tests.test_offer_list import an_entry_with_listings


def a_tree(client, token):
    """`Electronics` over `Phones`, with an alias and the entry and listings of a phone."""
    _, variant_id, *_ = an_entry_with_listings(client, token)
    variant = client.get(f"/api/admin/variants/{variant_id}", headers=auth(token)).json()
    phones = variant["category"]
    electronics = post(
        client, token, "/api/admin/categories", {"slug": "electronics", "name": "Electronics"}
    )
    client.patch(
        f"/api/admin/categories/{phones['id']}",
        headers=auth(token),
        json={"parent_id": electronics["id"]},
    )
    alias = post(
        client, token, f"/api/admin/categories/{phones['id']}/aliases", {"alias": "Telefons"}
    )
    return electronics, phones, alias, variant_id


def test_a_category_row_counts_what_it_holds_and_sorts_and_searches(client):
    token = admin_token(client)
    electronics, phones, *_ = a_tree(client, token)
    rows = client.get(
        "/api/admin/categories", headers=auth(token), params={"sort": "-variants_count"}
    ).json()["items"]
    first = rows[0]
    assert first["id"] == phones["id"]
    assert (first["products_count"], first["variants_count"], first["offers_count"]) == (1, 1, 3)
    assert (first["aliases_count"], first["attributes_count"]) == (1, 1)
    by_id = {row["id"]: row for row in rows}
    assert by_id[electronics["id"]]["children_count"] == 1

    # A name a shop gives it finds it.
    found = client.get("/api/admin/categories", headers=auth(token), params={"search": "telef"})
    assert [row["id"] for row in found.json()["items"]] == [phones["id"]]
    only = client.get(
        "/api/admin/categories", headers=auth(token), params={"ids": [electronics["id"]]}
    )
    assert [row["id"] for row in only.json()["items"]] == [electronics["id"]]


def test_the_tree_comes_whole_with_its_branch_totals(client):
    token = admin_token(client)
    electronics, phones, *_ = a_tree(client, token)
    roots = client.get("/api/admin/categories/tree", headers=auth(token)).json()
    top = next(node for node in roots if node["id"] == electronics["id"])
    assert top["variants_count"] == 0
    assert (top["branch_variants_count"], top["branch_offers_count"]) == (1, 3)
    assert [child["id"] for child in top["children"]] == [phones["id"]]


def test_an_alias_can_be_removed_from_its_own_category_only(client):
    token = admin_token(client)
    electronics, phones, alias, _ = a_tree(client, token)
    wrong = client.delete(
        f"/api/admin/categories/{electronics['id']}/aliases/{alias['id']}", headers=auth(token)
    )
    assert wrong.status_code == 404
    gone = client.delete(
        f"/api/admin/categories/{phones['id']}/aliases/{alias['id']}", headers=auth(token)
    )
    assert gone.status_code == 204
    left = client.get(f"/api/admin/categories/{phones['id']}/aliases", headers=auth(token))
    assert left.json() == []


def test_a_binding_names_its_attribute_and_an_entry_shows_its_attributes(client):
    token = admin_token(client)
    _, phones, _, variant_id = a_tree(client, token)
    bound = client.get(
        f"/api/admin/attributes/by-category/{phones['id']}", headers=auth(token)
    ).json()
    assert bound[0]["attribute"]["key"] == "storage_mb"
    assert bound[0]["attribute"]["unit_dimension"] == "MB"

    shown = client.get(f"/api/admin/variants/{variant_id}", headers=auth(token)).json()
    assert shown["attributes"] == [
        {
            "key": "storage_mb",
            "label": "Storage",
            "labels": {},
            "value": 262144,
            "display": "256 GB",
            "value_labels": {},
            "unit": "MB",
            "position": 0,
            "identity_bearing": True,
        }
    ]
