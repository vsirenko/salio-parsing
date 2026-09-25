"""A market as the panel lists it: its counts, the shops in it, the languages it may take."""

from tests.test_auth import auth
from tests.test_matching import admin_token
from tests.test_offer_list import an_entry_with_listings


def market(client, token, code="LV"):
    response = client.get(f"/api/admin/markets/{code}", headers=auth(token))
    assert response.status_code == 200, response.text
    return response.json()


def put_shop(client, token, shop_id, shown):
    response = client.put(
        f"/api/admin/shops/{shop_id}/markets/LV",
        headers=auth(token),
        json={"is_enabled": shown},
    )
    assert response.status_code == 200, response.text


def shops_in(client, token, state=None):
    params = {"market_code": "lv"} | ({"market_state": state} if state else {})
    response = client.get("/api/admin/shops", headers=auth(token), params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_a_market_counts_what_its_shown_shops_sell(client):
    token = admin_token(client)
    source, *_ = an_entry_with_listings(client, token)
    before = market(client, token)
    assert before["shops_attached"] == before["shops_shown"] == 0
    assert (before["offers_count"], before["products_count"]) == (0, 0)

    # Attached and hidden: counted as attached, and nothing it sells is on the storefront.
    put_shop(client, token, source["shop_id"], shown=False)
    hidden = market(client, token)
    assert (hidden["shops_attached"], hidden["shops_shown"], hidden["offers_count"]) == (1, 0, 0)

    put_shop(client, token, source["shop_id"], shown=True)
    shown = market(client, token)
    assert (shown["shops_attached"], shown["shops_shown"]) == (1, 1)
    assert (shown["offers_count"], shown["products_count"]) == (3, 1)
    [row] = client.get("/api/admin/markets", headers=auth(token)).json()["items"]
    assert row["offers_count"] == 3


def test_a_shop_row_says_where_it_is_attached_and_hidden(client):
    token = admin_token(client)
    source, *_ = an_entry_with_listings(client, token)
    put_shop(client, token, source["shop_id"], shown=False)

    assert shops_in(client, token) == []
    [attached] = shops_in(client, token, "attached")
    assert (attached["markets"], attached["hidden_markets"]) == ([], ["LV"])
    assert [row["id"] for row in shops_in(client, token, "hidden")] == [source["shop_id"]]

    put_shop(client, token, source["shop_id"], shown=True)
    [shown] = shops_in(client, token)
    assert (shown["markets"], shown["hidden_markets"]) == (["LV"], [])
    assert shops_in(client, token, "hidden") == []
    bad = client.get("/api/admin/shops", headers=auth(token), params={"market_state": "somewhere"})
    assert bad.status_code == 422


def test_a_language_is_one_iso_639_1_knows(client):
    token = admin_token(client)
    listed = client.get("/api/admin/markets/languages", headers=auth(token)).json()
    assert len(listed) == 183
    assert {"code": "lv", "name": "Latvian"} in listed
    refused = client.patch(
        "/api/admin/markets/LV", headers=auth(token), json={"languages": ["lv", "xx"]}
    )
    assert refused.status_code == 422
