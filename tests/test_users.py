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


# --- an administrator setting someone else's password ---


def test_an_admin_sets_a_colleague_s_password_and_ends_their_sessions(client):
    token = admin_token(client)
    user = create(client, token)
    old = {"email": NEW_USER["email"], "password": NEW_USER["password"]}
    theirs = tokens(client, old)

    reset = client.post(
        f"/api/admin/users/{user['id']}/password",
        headers=auth(token),
        json={"new_password": "brand-new-secret"},
    )
    assert reset.status_code == 200, reset.text
    assert "password" not in reset.text
    # Every session the account had is over, refresh tokens included.
    assert client.get("/api/auth/me", headers=auth(theirs["access_token"])).status_code == 401
    stale = client.post("/api/auth/refresh", json={"refresh_token": theirs["refresh_token"]})
    assert stale.status_code == 401
    assert client.post("/api/auth/login", json=old).status_code == 401
    assert (
        client.post("/api/auth/login", json={**old, "password": "brand-new-secret"}).status_code
        == 200
    )

    [entry] = client.get(
        "/api/admin/audit",
        headers=auth(token),
        params={"target_type": "user", "target_id": str(user["id"]), "path": "/password"},
    ).json()["items"]
    assert entry["changes"] == {"password_reset": True}


def test_your_own_password_is_changed_with_the_current_one(client):
    token = admin_token(client)
    me = client.get("/api/admin/auth/me", headers=auth(token)).json()
    refused = client.post(
        f"/api/admin/users/{me['id']}/password",
        headers=auth(token),
        json={"new_password": "brand-new-secret"},
    )
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "own_password")
    assert client.get("/api/admin/auth/me", headers=auth(token)).status_code == 200


def test_a_reset_password_has_the_same_rules_as_any_other(client):
    token = admin_token(client)
    user = create(client, token)
    url = f"/api/admin/users/{user['id']}/password"
    assert client.post(url, headers=auth(token), json={"new_password": "short"}).status_code == 422
    missing = client.post(
        "/api/admin/users/999999/password", headers=auth(token), json={"new_password": "x" * 9}
    )
    assert missing.status_code == 404


def test_users_are_found_by_email_or_name_and_by_whether_they_may_sign_in(client):
    token = admin_token(client)
    user = create(client, token)
    client.patch(f"/api/admin/users/{user['id']}", headers=auth(token), json={"is_active": False})

    def ids(**params):
        response = client.get("/api/admin/users", headers=auth(token), params=params)
        assert response.status_code == 200, response.text
        return [row["id"] for row in response.json()["items"]]

    assert ids(search="NEW@example") == [user["id"]]
    assert ids(search="new person") == [user["id"]]
    assert user["id"] in ids(is_active=False)
    assert user["id"] not in ids(is_active=True)


# --- accounts from the command line ---


def test_the_command_line_makes_an_account_once(event_loop):
    """Production seeds nothing, so a fresh server has no one to sign in as."""
    from app.features.users.cli import create
    from app.features.users.schemas import Role

    made = event_loop.run_until_complete(
        create("ops@example.com", Role.ADMIN, "Ops", "a-long-password")
    )
    assert made == "ops@example.com created as admin"
    again = event_loop.run_until_complete(
        create("ops@example.com", Role.ADMIN, "Ops", "another-password")
    )
    assert again == "ops@example.com exists, left as it is"


def test_a_copied_database_gets_the_server_s_worker_and_loses_the_demo_accounts(
    client, event_loop, monkeypatch
):
    """A database copied from a laptop brings the worker at the laptop's password and the
    demo accounts, whose passwords are in the repository."""
    from pydantic import SecretStr

    from app.core.config import settings
    from app.features.users.cli import ensure_worker, retire_demo

    monkeypatch.setattr(settings, "worker_password", SecretStr("the-server-s-own-secret"))
    assert event_loop.run_until_complete(ensure_worker()).endswith("configured password")
    signed = client.post(
        "/api/worker/auth/login",
        json={"email": settings.worker_email, "password": "the-server-s-own-secret"},
    )
    assert signed.status_code == 200, signed.text

    retired = event_loop.run_until_complete(retire_demo())
    assert "admin@example.com" in retired and settings.worker_email not in retired
    refused = client.post("/api/admin/auth/login", json=ADMIN)
    assert refused.status_code == 401
    assert event_loop.run_until_complete(retire_demo()) == []
