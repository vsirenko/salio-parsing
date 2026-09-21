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
