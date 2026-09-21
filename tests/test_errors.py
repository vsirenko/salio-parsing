"""The error envelope, and the probes.

Every failure leaves the API in the same shape, whichever endpoint produced it. These use
the countries reference data as a target because it is seeded and small; the assertions
are about the envelope, not about countries.
"""

from tests.test_auth import ADMIN, auth, tokens


def admin_token(client) -> str:
    return tokens(client, ADMIN, panel="/admin")["access_token"]


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_not_found(client):
    token = admin_token(client)
    response = client.get("/api/admin/countries/ZZ", headers=auth(token))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert "ZZ" in response.json()["error"]["message"]


def test_conflict(client):
    token = admin_token(client)
    response = client.post(
        "/api/admin/countries",
        headers=auth(token),
        json={"code": "LV", "name": "Latvia again", "currency_code": "EUR"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_validation_error_lists_the_fields(client):
    token = admin_token(client)
    response = client.post(
        "/api/admin/countries",
        headers=auth(token),
        json={"code": "TOOLONG", "name": "", "currency_code": "EUR"},
    )
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert {d["field"] for d in body["details"]} == {"code", "name"}


def test_unauthorized(client):
    response = client.get("/api/admin/countries")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_an_unknown_route_uses_the_same_envelope(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_error"
