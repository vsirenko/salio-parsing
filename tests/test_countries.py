"""Country and currency reference data.

The schema in the test database comes from the models, not from the migrations, so the
rows the migration seeds are re-created by the fixture. That is the one place these two
have to agree.
"""

from tests.test_auth import ADMIN, CUSTOMER, auth, tokens


def admin_token(client) -> str:
    return tokens(client, ADMIN, panel="/admin")["access_token"]


# --- currencies ---


def test_list_currencies(client):
    token = admin_token(client)
    body = client.get("/api/admin/currencies", headers=auth(token)).json()
    assert body["total"] == 1
    assert body["items"][0] == {
        "code": "EUR",
        "name": "Euro",
        "symbol": "€",
        "minor_units": 2,
    }


def test_currencies_are_read_only(client):
    token = admin_token(client)
    response = client.post(
        "/api/admin/currencies", headers=auth(token), json={"code": "USD", "name": "Dollar"}
    )
    assert response.status_code == 405


# --- countries ---


def test_list_countries(client):
    token = admin_token(client)
    body = client.get("/api/admin/countries", headers=auth(token)).json()
    assert body["total"] == 3
    assert [c["code"] for c in body["items"]] == ["EE", "LT", "LV"]


def test_seeded_countries_have_no_vat_rate(client):
    """Left unknown on purpose — a wrong rate explains a price difference wrongly."""
    token = admin_token(client)
    body = client.get("/api/admin/countries/LV", headers=auth(token)).json()
    assert body["vat_standard_rate"] is None
    assert body["currency_code"] == "EUR"
    assert body["is_eu"] is True


def test_get_country_is_case_insensitive(client):
    token = admin_token(client)
    assert client.get("/api/admin/countries/lv", headers=auth(token)).status_code == 200


def test_get_unknown_country(client):
    token = admin_token(client)
    response = client.get("/api/admin/countries/ZZ", headers=auth(token))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_filter_by_eu_membership(client):
    token = admin_token(client)
    client.post(
        "/api/admin/countries",
        headers=auth(token),
        json={"code": "NO", "name": "Norway", "currency_code": "EUR", "is_eu": False},
    )

    inside = client.get("/api/admin/countries?is_eu=true", headers=auth(token)).json()
    outside = client.get("/api/admin/countries?is_eu=false", headers=auth(token)).json()
    assert inside["total"] == 3
    assert [c["code"] for c in outside["items"]] == ["NO"]


def test_set_and_withdraw_the_vat_rate(client):
    token = admin_token(client)

    set_rate = client.patch(
        "/api/admin/countries/LV", headers=auth(token), json={"vat_standard_rate": "0.21"}
    )
    assert set_rate.status_code == 200, set_rate.text
    assert set_rate.json()["vat_standard_rate"] == "0.2100"

    # Null puts it back to unknown, which is how a wrong rate is withdrawn rather than
    # replaced by another guess.
    cleared = client.patch(
        "/api/admin/countries/LV", headers=auth(token), json={"vat_standard_rate": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["vat_standard_rate"] is None


def test_the_rate_is_a_fraction_not_a_percentage(client):
    token = admin_token(client)
    response = client.patch(
        "/api/admin/countries/LV", headers=auth(token), json={"vat_standard_rate": "21"}
    )
    assert response.status_code == 422


def test_country_code_is_not_editable(client):
    token = admin_token(client)
    response = client.patch("/api/admin/countries/LV", headers=auth(token), json={"code": "XX"})
    assert response.status_code == 422


def test_unknown_currency_is_refused_by_name(client):
    token = admin_token(client)
    response = client.patch(
        "/api/admin/countries/LV", headers=auth(token), json={"currency_code": "XYZ"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_currency"
    assert "XYZ" in response.json()["error"]["message"]


def test_create_country(client):
    token = admin_token(client)
    response = client.post(
        "/api/admin/countries",
        headers=auth(token),
        json={"code": "de", "name": "Germany", "currency_code": "eur", "is_eu": True},
    )
    assert response.status_code == 201, response.text
    assert response.json()["code"] == "DE"
    assert response.json()["currency_code"] == "EUR"


def test_create_duplicate_country(client):
    token = admin_token(client)
    response = client.post(
        "/api/admin/countries",
        headers=auth(token),
        json={"code": "LV", "name": "Latvia again", "currency_code": "EUR"},
    )
    assert response.status_code == 409


def test_create_with_unknown_currency(client):
    token = admin_token(client)
    response = client.post(
        "/api/admin/countries",
        headers=auth(token),
        json={"code": "GB", "name": "United Kingdom", "currency_code": "GBP"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_currency"


# --- guards and the trail ---


def test_reference_data_requires_an_admin_token(client):
    user_token = tokens(client, CUSTOMER)["access_token"]
    assert client.get("/api/admin/countries", headers=auth(user_token)).status_code == 401
    assert client.get("/api/admin/currencies").status_code == 401


def test_a_rate_change_is_recorded_in_the_audit_trail(client):
    token = admin_token(client)
    client.patch("/api/admin/countries/EE", headers=auth(token), json={"vat_standard_rate": "0.24"})

    entries = client.get(
        "/api/admin/audit", headers=auth(token), params={"path": "/countries/"}
    ).json()["items"]
    entry = next(e for e in entries if e["method"] == "PATCH")
    assert entry["target_type"] == "country"
    assert entry["target_id"] == "EE"
    assert entry["changes"] == {"vat_standard_rate": "0.24"}


def test_a_refused_change_still_names_its_target(client):
    token = admin_token(client)
    client.patch("/api/admin/countries/EE", headers=auth(token), json={"currency_code": "XYZ"})

    entries = client.get(
        "/api/admin/audit", headers=auth(token), params={"outcome": "failure"}
    ).json()["items"]
    refused = next(e for e in entries if e["status_code"] == 422)
    assert refused["target_type"] == "country"
    assert refused["target_id"] == "EE"
    assert refused["changes"] is None
