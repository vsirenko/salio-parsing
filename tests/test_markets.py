"""Markets: the storefronts we run.

Nothing is seeded — a market is a decision, not a fact about the world — so every test
here opens the one it needs.
"""

from tests.test_auth import ADMIN, CUSTOMER, auth, tokens

LATVIA = {"code": "LV", "name": "Latvia", "slug": "latvija", "languages": ["lv", "ru", "en"]}


def admin_token(client) -> str:
    return tokens(client, ADMIN, panel="/admin")["access_token"]


def open_market(client, token: str, **overrides):
    return client.post("/api/admin/markets", headers=auth(token), json={**LATVIA, **overrides})


def test_no_markets_until_one_is_opened(client):
    token = admin_token(client)
    assert client.get("/api/admin/markets", headers=auth(token)).json()["total"] == 0


def test_open_a_market(client):
    token = admin_token(client)
    response = open_market(client, token, code="lv")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["code"] == "LV"
    assert body["slug"] == "latvija"
    assert body["languages"] == ["lv", "ru", "en"]
    # Created, not shown: the parsers and the category mapping come first.
    assert body["is_enabled"] is False


def test_a_market_needs_its_country_first(client):
    token = admin_token(client)
    response = open_market(client, token, code="DE", slug="deutschland")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_country"


def test_one_market_per_country(client):
    token = admin_token(client)
    assert open_market(client, token).status_code == 201
    again = open_market(client, token, name="Latvia again", slug="latvia-2")
    assert again.status_code == 409


def test_slug_is_unique_across_markets(client):
    token = admin_token(client)
    assert open_market(client, token).status_code == 201
    clash = open_market(client, token, code="LT", name="Lithuania", slug="latvija")
    assert clash.status_code == 409


def test_enabling_is_what_makes_it_visible(client):
    token = admin_token(client)
    open_market(client, token)

    response = client.patch("/api/admin/markets/lv", headers=auth(token), json={"is_enabled": True})
    assert response.status_code == 200
    assert response.json()["is_enabled"] is True

    enabled = client.get("/api/admin/markets?is_enabled=true", headers=auth(token)).json()
    assert [m["code"] for m in enabled["items"]] == ["LV"]


def test_get_is_case_insensitive(client):
    token = admin_token(client)
    open_market(client, token)
    assert client.get("/api/admin/markets/lv", headers=auth(token)).status_code == 200


def test_get_unknown_market(client):
    token = admin_token(client)
    assert client.get("/api/admin/markets/ZZ", headers=auth(token)).status_code == 404


# --- what the shape rules refuse ---


def test_a_malformed_slug_is_refused(client):
    token = admin_token(client)
    for bad in ("Latvija", "lat vija", "-lv", "lv-", "lv--x"):
        assert open_market(client, token, slug=bad).status_code == 422, bad


def test_languages_must_be_iso_codes_and_distinct(client):
    token = admin_token(client)
    assert open_market(client, token, languages=["lav"]).status_code == 422
    assert open_market(client, token, languages=["lv", "lv"]).status_code == 422
    assert open_market(client, token, languages=[]).status_code == 422


def test_languages_are_normalised_not_rejected(client):
    """Case and padding are the caller being sloppy, not the caller being wrong."""
    token = admin_token(client)
    body = open_market(client, token, languages=["LV", " ru "]).json()
    assert body["languages"] == ["lv", "ru"]


def test_the_code_is_not_editable(client):
    token = admin_token(client)
    open_market(client, token)
    response = client.patch("/api/admin/markets/LV", headers=auth(token), json={"code": "LT"})
    assert response.status_code == 422


def test_moving_a_slug_onto_a_taken_one(client):
    token = admin_token(client)
    open_market(client, token)
    open_market(client, token, code="LT", name="Lithuania", slug="lietuva")

    response = client.patch("/api/admin/markets/LT", headers=auth(token), json={"slug": "latvija"})
    assert response.status_code == 409


# --- guards and the trail ---


def test_markets_require_an_admin_token(client):
    user_token = tokens(client, CUSTOMER)["access_token"]
    assert client.get("/api/admin/markets", headers=auth(user_token)).status_code == 401
    assert client.get("/api/admin/markets").status_code == 401


def test_opening_a_market_is_recorded(client):
    token = admin_token(client)
    open_market(client, token)

    entries = client.get(
        "/api/admin/audit", headers=auth(token), params={"path": "/markets"}
    ).json()["items"]
    entry = next(e for e in entries if e["method"] == "POST" and e["status_code"] == 201)
    assert entry["target_type"] == "market"
    assert entry["target_id"] == "LV"
    assert entry["changes"]["slug"] == "latvija"
    assert entry["changes"]["languages"] == ["lv", "ru", "en"]
