"""Admin user management."""

from tests.test_auth import ADMIN, CUSTOMER, auth, tokens

NEW_USER = {"email": "new@example.com", "password": "password123", "full_name": "New Person"}


def admin_token(client) -> str:
    return tokens(client, ADMIN, panel="/admin")["access_token"]


def create(client, token: str, **overrides) -> dict:
    response = client.post("/api/admin/users", headers=auth(token), json={**NEW_USER, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def test_update_name(client):
    token = admin_token(client)
    user = create(client, token)

    response = client.patch(
        f"/api/admin/users/{user['id']}", headers=auth(token), json={"full_name": "Renamed"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["full_name"] == "Renamed"
    # Untouched fields stay as they were.
    assert response.json()["role"] == "customer"
    assert response.json()["is_active"] is True


def test_full_name_can_be_cleared(client):
    token = admin_token(client)
    user = create(client, token)

    response = client.patch(
        f"/api/admin/users/{user['id']}", headers=auth(token), json={"full_name": None}
    )
    assert response.status_code == 200
    assert response.json()["full_name"] is None


def test_empty_patch_changes_nothing(client):
    token = admin_token(client)
    user = create(client, token)

    response = client.patch(f"/api/admin/users/{user['id']}", headers=auth(token), json={})
    assert response.status_code == 200
    assert response.json() == user


def test_promotion_moves_the_account_to_the_other_panel(client):
    token = admin_token(client)
    user = create(client, token)

    promoted = client.patch(
        f"/api/admin/users/{user['id']}", headers=auth(token), json={"role": "admin"}
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"

    credentials = {"email": NEW_USER["email"], "password": NEW_USER["password"]}
    assert client.post("/api/auth/login", json=credentials).status_code == 401
    assert client.post("/api/admin/auth/login", json=credentials).status_code == 200


def test_deactivation_ends_the_session(client):
    token = admin_token(client)
    user = create(client, token)
    credentials = {"email": NEW_USER["email"], "password": NEW_USER["password"]}
    theirs = tokens(client, credentials)["access_token"]
    assert client.get("/api/auth/me", headers=auth(theirs)).status_code == 200

    response = client.patch(
        f"/api/admin/users/{user['id']}", headers=auth(token), json={"is_active": False}
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert client.get("/api/auth/me", headers=auth(theirs)).status_code == 401


def test_reactivation_does_not_revive_old_tokens(client):
    token = admin_token(client)
    user = create(client, token)
    credentials = {"email": NEW_USER["email"], "password": NEW_USER["password"]}
    theirs = tokens(client, credentials)

    for is_active in (False, True):
        response = client.patch(
            f"/api/admin/users/{user['id']}", headers=auth(token), json={"is_active": is_active}
        )
        assert response.status_code == 200

    assert client.get("/api/auth/me", headers=auth(theirs["access_token"])).status_code == 401
    stale = client.post("/api/auth/refresh", json={"refresh_token": theirs["refresh_token"]})
    assert stale.status_code == 401
    # Signing in again works — it is the old tokens that are gone, not the account.
    assert client.post("/api/auth/login", json=credentials).status_code == 200


def test_admin_cannot_disable_themselves(client):
    token = admin_token(client)
    me = client.get("/api/admin/auth/me", headers=auth(token)).json()

    response = client.patch(
        f"/api/admin/users/{me['id']}", headers=auth(token), json={"is_active": False}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "self_lockout"


def test_admin_cannot_demote_themselves(client):
    token = admin_token(client)
    me = client.get("/api/admin/auth/me", headers=auth(token)).json()

    response = client.patch(
        f"/api/admin/users/{me['id']}", headers=auth(token), json={"role": "customer"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "self_lockout"


def test_admin_may_edit_their_own_name(client):
    """Only removing your own access is refused, not every self-edit."""
    token = admin_token(client)
    me = client.get("/api/admin/auth/me", headers=auth(token)).json()

    response = client.patch(
        f"/api/admin/users/{me['id']}", headers=auth(token), json={"full_name": "Still Admin"}
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "Still Admin"


def test_update_unknown_user(client):
    token = admin_token(client)
    response = client.patch("/api/admin/users/999", headers=auth(token), json={"full_name": "X"})
    assert response.status_code == 404


def test_password_is_not_editable_through_patch(client):
    token = admin_token(client)
    user = create(client, token)

    response = client.patch(
        f"/api/admin/users/{user['id']}", headers=auth(token), json={"password": "hunter2000"}
    )
    assert response.status_code == 422


def test_update_requires_an_admin_token(client):
    user_token = tokens(client, CUSTOMER)["access_token"]
    response = client.patch("/api/admin/users/1", headers=auth(user_token), json={"full_name": "X"})
    assert response.status_code == 401


def test_update_is_recorded_in_the_audit_trail(client):
    token = admin_token(client)
    user = create(client, token)
    client.patch(
        f"/api/admin/users/{user['id']}", headers=auth(token), json={"full_name": "Renamed"}
    )

    entries = client.get(
        "/api/admin/audit", headers=auth(token), params={"path": "/users/"}
    ).json()["items"]
    entry = next(e for e in entries if e["method"] == "PATCH")
    assert entry["target_type"] == "user"
    assert entry["target_id"] == str(user["id"])
    assert entry["changes"] == {"full_name": "Renamed"}


def test_a_refused_edit_still_names_its_target(client):
    token = admin_token(client)
    me = client.get("/api/admin/auth/me", headers=auth(token)).json()
    client.patch(f"/api/admin/users/{me['id']}", headers=auth(token), json={"is_active": False})

    entries = client.get(
        "/api/admin/audit", headers=auth(token), params={"outcome": "failure"}
    ).json()["items"]
    refused = next(e for e in entries if e["status_code"] == 409)
    assert refused["target_type"] == "user"
    assert refused["target_id"] == str(me["id"])
    # Nothing was applied, so nothing is recorded as changed.
    assert refused["changes"] is None
