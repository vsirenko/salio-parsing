"""Auth tests, focused on the boundary between the two panels."""

ADMIN = {"email": "admin@example.com", "password": "admin-password"}
CUSTOMER = {"email": "customer@example.com", "password": "customer-password"}


def tokens(client, credentials, *, panel="") -> dict:
    response = client.post(f"/api{panel}/auth/login", json=credentials)
    assert response.status_code == 200, response.text
    return response.json()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- sign-in ---


def test_customer_login(client):
    body = tokens(client, CUSTOMER)
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]


def test_admin_login(client):
    assert tokens(client, ADMIN, panel="/admin")["access_token"]


def test_wrong_password(client):
    response = client.post("/api/auth/login", json={**CUSTOMER, "password": "nope"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_unknown_email_is_indistinguishable(client):
    response = client.post(
        "/api/auth/login", json={"email": "ghost@example.com", "password": "whatever"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid credentials"


# --- the panels are separate ---


def test_admin_cannot_use_the_client_login(client):
    response = client.post("/api/auth/login", json=ADMIN)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "wrong_panel"


def test_customer_cannot_use_the_admin_login(client):
    response = client.post("/api/admin/auth/login", json=CUSTOMER)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "wrong_panel"


def test_client_token_is_rejected_by_the_admin_api(client):
    token = tokens(client, CUSTOMER)["access_token"]
    response = client.get("/api/admin/users", headers=auth(token))
    assert response.status_code == 401


def test_admin_token_is_rejected_by_the_client_api(client):
    token = tokens(client, ADMIN, panel="/admin")["access_token"]
    response = client.get("/api/auth/me", headers=auth(token))
    assert response.status_code == 401


# --- guards ---


def test_admin_api_requires_a_token(client):
    assert client.get("/api/admin/users").status_code == 401


def test_admin_api_with_admin_token(client):
    token = tokens(client, ADMIN, panel="/admin")["access_token"]
    response = client.get("/api/admin/users", headers=auth(token))
    assert response.status_code == 200
    assert response.json()["total"] == 2


def test_garbage_token(client):
    assert client.get("/api/auth/me", headers=auth("not-a-jwt")).status_code == 401


def test_refresh_token_cannot_be_used_as_access_token(client):
    refresh = tokens(client, CUSTOMER)["refresh_token"]
    response = client.get("/api/auth/me", headers=auth(refresh))
    assert response.status_code == 401


# --- session ---


def test_me(client):
    token = tokens(client, CUSTOMER)["access_token"]
    body = client.get("/api/auth/me", headers=auth(token)).json()
    assert body["email"] == CUSTOMER["email"]
    assert body["role"] == "customer"
    assert "password_hash" not in body


def test_refresh_returns_a_new_pair(client):
    refresh = tokens(client, CUSTOMER)["refresh_token"]
    response = client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert response.status_code == 200
    assert (
        client.get("/api/auth/me", headers=auth(response.json()["access_token"])).status_code == 200
    )


def test_disabled_account_cannot_sign_in(client):
    token = tokens(client, ADMIN, panel="/admin")["access_token"]
    created = client.post(
        "/api/admin/users",
        headers=auth(token),
        json={"email": "Blocked@Example.com ", "password": "password123", "is_active": False},
    )
    assert created.status_code == 201
    assert created.json()["email"] == "blocked@example.com"

    response = client.post(
        "/api/auth/login", json={"email": "blocked@example.com", "password": "password123"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "account_disabled"


def test_admin_cannot_be_created_through_the_client_api(client):
    # There is no public registration endpoint at all.
    assert client.post("/api/auth/register", json=CUSTOMER).status_code == 404


# --- revocation ---


def test_disabled_account_cannot_refresh(client):
    """A signature that still verifies is not a reason to hand out a fresh pair."""
    admin = tokens(client, ADMIN, panel="/admin")["access_token"]
    created = client.post(
        "/api/admin/users",
        headers=auth(admin),
        json={"email": "soon-gone@example.com", "password": "password123"},
    )
    assert created.status_code == 201
    refresh = tokens(client, {"email": "soon-gone@example.com", "password": "password123"})[
        "refresh_token"
    ]

    disabled = client.patch(
        f"/api/admin/users/{created.json()['id']}",
        headers=auth(admin),
        json={"is_active": False},
    )
    assert disabled.status_code == 200

    response = client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert response.status_code == 401


def test_password_change_keeps_this_session_and_ends_the_others(client):
    first = tokens(client, CUSTOMER)
    second = tokens(client, CUSTOMER)

    response = client.post(
        "/api/auth/password",
        headers=auth(first["access_token"]),
        json={"current_password": CUSTOMER["password"], "new_password": "brand-new-password"},
    )
    assert response.status_code == 200, response.text
    fresh = response.json()

    # The pair handed back works...
    assert client.get("/api/auth/me", headers=auth(fresh["access_token"])).status_code == 200
    # ...and every token minted before the change is dead, access and refresh alike.
    for dead in (first["access_token"], second["access_token"]):
        assert client.get("/api/auth/me", headers=auth(dead)).status_code == 401
    stale = client.post("/api/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert stale.status_code == 401
    assert stale.json()["error"]["code"] == "session_revoked"


def test_password_change_takes_effect_at_sign_in(client):
    token = tokens(client, CUSTOMER)["access_token"]
    client.post(
        "/api/auth/password",
        headers=auth(token),
        json={"current_password": CUSTOMER["password"], "new_password": "brand-new-password"},
    )

    assert client.post("/api/auth/login", json=CUSTOMER).status_code == 401
    assert (
        client.post(
            "/api/auth/login",
            json={"email": CUSTOMER["email"], "password": "brand-new-password"},
        ).status_code
        == 200
    )


def test_password_change_needs_the_current_password(client):
    token = tokens(client, CUSTOMER)["access_token"]
    response = client.post(
        "/api/auth/password",
        headers=auth(token),
        json={"current_password": "not-it", "new_password": "brand-new-password"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_current_password"


def test_password_change_must_actually_change_it(client):
    token = tokens(client, CUSTOMER)["access_token"]
    response = client.post(
        "/api/auth/password",
        headers=auth(token),
        json={"current_password": CUSTOMER["password"], "new_password": CUSTOMER["password"]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "password_unchanged"


def test_admin_changes_own_password(client):
    token = tokens(client, ADMIN, panel="/admin")["access_token"]
    response = client.post(
        "/api/admin/auth/password",
        headers=auth(token),
        json={"current_password": ADMIN["password"], "new_password": "brand-new-password"},
    )
    assert response.status_code == 200, response.text
    assert (
        client.get("/api/admin/auth/me", headers=auth(response.json()["access_token"])).status_code
        == 200
    )


def test_password_change_requires_a_token(client):
    response = client.post(
        "/api/auth/password",
        json={"current_password": CUSTOMER["password"], "new_password": "brand-new-password"},
    )
    assert response.status_code == 401


def test_a_refused_password_change_still_names_its_target(client):
    token = tokens(client, ADMIN, panel="/admin")["access_token"]
    me = client.get("/api/admin/auth/me", headers=auth(token)).json()
    client.post(
        "/api/admin/auth/password",
        headers=auth(token),
        json={"current_password": "not-it", "new_password": "brand-new-password"},
    )

    entries = client.get(
        "/api/admin/audit", headers=auth(token), params={"path": "/auth/password"}
    ).json()["items"]
    assert entries[0]["status_code"] == 422
    assert entries[0]["target_type"] == "user"
    assert entries[0]["target_id"] == str(me["id"])
    assert entries[0]["changes"] is None
