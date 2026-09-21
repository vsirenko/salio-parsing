"""The category tree and the visibility that cascades down it."""

from tests.test_auth import ADMIN, CUSTOMER, auth, tokens


def admin_token(client) -> str:
    return tokens(client, ADMIN, panel="/admin")["access_token"]


def add(client, token: str, slug: str, name: str, parent_id: int | None = None, **extra):
    response = client.post(
        "/api/admin/categories",
        headers=auth(token),
        json={"slug": slug, "name": name, "parent_id": parent_id, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def read(client, token: str, category_id: int) -> dict:
    return client.get(f"/api/admin/categories/{category_id}", headers=auth(token)).json()


def branch(client, token: str) -> tuple[dict, dict, dict]:
    """Electronics > Phones > Smartphones."""
    top = add(client, token, "electronics", "Electronics")
    mid = add(client, token, "phones", "Phones", top["id"])
    leaf = add(client, token, "smartphones", "Smartphones", mid["id"])
    return top, mid, leaf


# --- the tree ---


def test_add_a_root_and_a_child(client):
    token = admin_token(client)
    top = add(client, token, "electronics", "Electronics")
    child = add(client, token, "phones", "Phones", top["id"])
    assert top["parent_id"] is None
    assert child["parent_id"] == top["id"]


def test_list_roots_and_children(client):
    token = admin_token(client)
    top, mid, _ = branch(client, token)

    roots = client.get("/api/admin/categories?roots_only=true", headers=auth(token)).json()
    assert [c["slug"] for c in roots["items"]] == ["electronics"]

    children = client.get(
        f"/api/admin/categories?parent_id={top['id']}", headers=auth(token)
    ).json()
    assert [c["slug"] for c in children["items"]] == ["phones"]
    assert mid["id"] == children["items"][0]["id"]


def test_unknown_parent(client):
    token = admin_token(client)
    response = client.post(
        "/api/admin/categories",
        headers=auth(token),
        json={"slug": "orphan", "name": "Orphan", "parent_id": 999},
    )
    assert response.status_code == 404


def test_slug_is_unique(client):
    token = admin_token(client)
    add(client, token, "electronics", "Electronics")
    response = client.post(
        "/api/admin/categories", headers=auth(token), json={"slug": "electronics", "name": "Again"}
    )
    assert response.status_code == 409


def test_a_malformed_slug_is_refused(client):
    token = admin_token(client)
    for bad in ("Electronics", "home appliances", "-x", "x-", "x--y"):
        response = client.post(
            "/api/admin/categories", headers=auth(token), json={"slug": bad, "name": "X"}
        )
        assert response.status_code == 422, bad


# --- visibility cascades ---


def test_hiding_a_parent_hides_everything_under_it(client):
    token = admin_token(client)
    top, mid, leaf = branch(client, token)

    response = client.patch(
        f"/api/admin/categories/{top['id']}", headers=auth(token), json={"is_visible": False}
    )
    assert response.status_code == 200

    for node in (top, mid, leaf):
        assert read(client, token, node["id"])["is_visible_effective"] is False

    # Only the parent was actually hidden; the children were never edited.
    assert read(client, token, mid["id"])["is_visible"] is True
    assert read(client, token, leaf["id"])["is_visible"] is True


def test_unhiding_restores_the_branch(client):
    token = admin_token(client)
    top, mid, leaf = branch(client, token)
    client.patch(
        f"/api/admin/categories/{top['id']}", headers=auth(token), json={"is_visible": False}
    )
    client.patch(
        f"/api/admin/categories/{top['id']}", headers=auth(token), json={"is_visible": True}
    )

    for node in (top, mid, leaf):
        assert read(client, token, node["id"])["is_visible_effective"] is True


def test_hiding_a_middle_node_leaves_its_parent_alone(client):
    token = admin_token(client)
    top, mid, leaf = branch(client, token)
    client.patch(
        f"/api/admin/categories/{mid['id']}", headers=auth(token), json={"is_visible": False}
    )

    assert read(client, token, top["id"])["is_visible_effective"] is True
    assert read(client, token, mid["id"])["is_visible_effective"] is False
    assert read(client, token, leaf["id"])["is_visible_effective"] is False


def test_a_child_added_under_a_hidden_parent_is_hidden_at_once(client):
    token = admin_token(client)
    top = add(client, token, "electronics", "Electronics", is_visible=False)
    child = add(client, token, "phones", "Phones", top["id"])
    assert child["is_visible_effective"] is False


def test_moving_a_branch_recomputes_it(client):
    token = admin_token(client)
    hidden = add(client, token, "hidden", "Hidden", is_visible=False)
    _, mid, leaf = branch(client, token)

    response = client.patch(
        f"/api/admin/categories/{mid['id']}", headers=auth(token), json={"parent_id": hidden["id"]}
    )
    assert response.status_code == 200
    assert read(client, token, mid["id"])["is_visible_effective"] is False
    assert read(client, token, leaf["id"])["is_visible_effective"] is False


def test_moving_to_the_root_is_expressible(client):
    token = admin_token(client)
    top, mid, _ = branch(client, token)
    client.patch(
        f"/api/admin/categories/{top['id']}", headers=auth(token), json={"is_visible": False}
    )

    response = client.patch(
        f"/api/admin/categories/{mid['id']}", headers=auth(token), json={"parent_id": None}
    )
    assert response.status_code == 200
    assert response.json()["parent_id"] is None
    assert read(client, token, mid["id"])["is_visible_effective"] is True


def test_filter_by_effective_visibility(client):
    token = admin_token(client)
    top, _, _ = branch(client, token)
    client.patch(
        f"/api/admin/categories/{top['id']}", headers=auth(token), json={"is_visible": False}
    )

    shown = client.get(
        "/api/admin/categories?is_visible_effective=true", headers=auth(token)
    ).json()
    assert shown["total"] == 0


# --- loops ---


def test_a_category_cannot_become_its_own_descendant(client):
    token = admin_token(client)
    top, _, leaf = branch(client, token)

    response = client.patch(
        f"/api/admin/categories/{top['id']}", headers=auth(token), json={"parent_id": leaf["id"]}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "category_cycle"


def test_a_category_cannot_be_its_own_parent(client):
    token = admin_token(client)
    top = add(client, token, "electronics", "Electronics")

    response = client.patch(
        f"/api/admin/categories/{top['id']}", headers=auth(token), json={"parent_id": top["id"]}
    )
    assert response.status_code == 422


# --- the two states are independent ---


def test_identity_ready_is_not_visibility(client):
    """A category can be shown long before the parser understands it."""
    token = admin_token(client)
    top = add(client, token, "electronics", "Electronics")
    assert top["identity_ready"] is False
    assert top["is_visible_effective"] is True

    client.patch(
        f"/api/admin/categories/{top['id']}", headers=auth(token), json={"identity_ready": True}
    )
    body = read(client, token, top["id"])
    assert body["identity_ready"] is True
    assert body["is_visible_effective"] is True


def test_effective_visibility_cannot_be_set_by_hand(client):
    token = admin_token(client)
    top = add(client, token, "electronics", "Electronics")
    response = client.patch(
        f"/api/admin/categories/{top['id']}",
        headers=auth(token),
        json={"is_visible_effective": False},
    )
    assert response.status_code == 422


# --- guards and the trail ---


def test_categories_require_an_admin_token(client):
    user_token = tokens(client, CUSTOMER)["access_token"]
    assert client.get("/api/admin/categories", headers=auth(user_token)).status_code == 401
    assert client.get("/api/admin/categories").status_code == 401


def test_hiding_is_recorded(client):
    token = admin_token(client)
    top = add(client, token, "electronics", "Electronics")
    client.patch(
        f"/api/admin/categories/{top['id']}", headers=auth(token), json={"is_visible": False}
    )

    entries = client.get(
        "/api/admin/audit", headers=auth(token), params={"path": "/categories/"}
    ).json()["items"]
    entry = next(e for e in entries if e["method"] == "PATCH")
    assert entry["target_type"] == "category"
    assert entry["target_id"] == str(top["id"])
    assert entry["changes"] == {"is_visible": False}
