"""The price history: a fact about a listing, written only when something moves."""

from tests.test_auth import ADMIN, CUSTOMER, auth, tokens
from tests.test_offers import FEED_ROW, ingest, setup_source


def admin_token(client) -> str:
    return tokens(client, ADMIN, panel="/admin")["access_token"]


def history(client, token, **params) -> dict:
    return client.get("/api/admin/price-history", headers=auth(token), params=params).json()


def stock(client, token, **params) -> dict:
    return client.get("/api/admin/availability-history", headers=auth(token), params=params).json()


def priced(payload: dict, price: str) -> dict:
    return {**payload, "price": price}


# --- what gets written ---


def test_the_first_observation_starts_the_series(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    result = ingest(
        client,
        token,
        source["id"],
        {"external_id": "SKU-1", "market_code": "LV", "payload": FEED_ROW},
    )

    rows = history(client, token)["items"]
    assert len(rows) == 1
    assert rows[0]["offer_id"] == result["offer_id"]
    assert rows[0]["price"] == "1179.00"
    assert rows[0]["currency_code"] == "EUR"
    # Nothing is matched yet, and the row does not need it to be.
    assert rows[0]["variant_id"] is None
    # The stock state is recorded too, in its own series.
    assert stock(client, token)["items"][0]["availability"] == "in_stock"


def test_an_unchanged_price_writes_nothing(client):
    """Changes, never snapshots — a million offers photographed daily would be 365 million
    rows a year, almost all repeating the row before."""
    token = admin_token(client)
    _, source = setup_source(client, token)
    body = {"external_id": "SKU-1", "market_code": "LV", "payload": FEED_ROW}

    ingest(client, token, source["id"], body)
    ingest(client, token, source["id"], body)
    # A page that changed somewhere else entirely, at the same price.
    ingest(
        client,
        token,
        source["id"],
        {**body, "payload": {**FEED_ROW, "name": "Apple iPhone 15 Pro 256GB — new photo"}},
    )

    assert history(client, token)["total"] == 1


def test_a_moved_price_is_a_new_row(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    body = {"external_id": "SKU-1", "market_code": "LV", "payload": FEED_ROW}

    ingest(client, token, source["id"], body)
    ingest(client, token, source["id"], {**body, "payload": priced(FEED_ROW, "999,00")})
    ingest(client, token, source["id"], {**body, "payload": priced(FEED_ROW, "1049,00")})

    rows = history(client, token)["items"]
    # Newest first.
    assert [r["price"] for r in rows] == ["1049.00", "999.00", "1179.00"]


def test_stock_is_its_own_series(client):
    """Availability arrives through channels that carry no price, so recording it as a
    price event would mean repeating the last known price and calling it an observation."""
    token = admin_token(client)
    _, source = setup_source(client, token)
    body = {"external_id": "SKU-1", "market_code": "LV", "payload": FEED_ROW}

    ingest(client, token, source["id"], body)
    ingest(
        client,
        token,
        source["id"],
        {**body, "payload": {**FEED_ROW, "available": "false"}},
    )

    # The stock flipped twice and the price never moved.
    assert [r["availability"] for r in stock(client, token)["items"]] == [
        "out_of_stock",
        "in_stock",
    ]
    assert history(client, token)["total"] == 1


def test_a_price_move_does_not_write_a_stock_row(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    body = {"external_id": "SKU-1", "market_code": "LV", "payload": FEED_ROW}

    ingest(client, token, source["id"], body)
    ingest(client, token, source["id"], {**body, "payload": priced(FEED_ROW, "999,00")})

    assert history(client, token)["total"] == 2
    assert stock(client, token)["total"] == 1


def test_both_series_say_which_channel_reported(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    ingest(
        client,
        token,
        source["id"],
        {"external_id": "SKU-1", "market_code": "LV", "payload": FEED_ROW},
    )

    assert history(client, token)["items"][0]["source_id"] == source["id"]
    assert stock(client, token)["items"][0]["source_id"] == source["id"]


def test_the_row_carries_what_a_chart_groups_by(client):
    token = admin_token(client)
    shop, source = setup_source(client, token)
    ingest(
        client,
        token,
        source["id"],
        {"external_id": "SKU-1", "market_code": "LV", "payload": FEED_ROW},
    )

    row = history(client, token)["items"][0]
    sellers = client.get(f"/api/admin/shops/{shop['id']}/sellers", headers=auth(token)).json()
    assert row["seller_id"] == sellers[0]["id"]
    assert row["market_code"] == "LV"
    assert row["condition"] == "new"


# --- two listings of the same thing stay two series ---


def test_two_sellers_are_two_series(client):
    token = admin_token(client)
    _, source = setup_source(client, token, marketplace=True)
    base = {"external_id": "SKU-1", "market_code": "LV", "payload": FEED_ROW}
    one = ingest(client, token, source["id"], {**base, "seller_external_id": "trader-1"})
    ingest(
        client,
        token,
        source["id"],
        {
            **base,
            "seller_external_id": "trader-2",
            "payload": priced(FEED_ROW, "1099,00"),
        },
    )

    assert history(client, token)["total"] == 2
    mine = history(client, token, offer_id=one["offer_id"])
    assert mine["total"] == 1
    assert mine["items"][0]["price"] == "1179.00"


# --- reading it back ---


def test_filter_by_listing(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    first = ingest(
        client,
        token,
        source["id"],
        {"external_id": "SKU-1", "market_code": "LV", "payload": FEED_ROW},
    )
    ingest(
        client,
        token,
        source["id"],
        {"external_id": "SKU-2", "market_code": "LV", "payload": priced(FEED_ROW, "500,00")},
    )

    only = history(client, token, offer_id=first["offer_id"])
    assert only["total"] == 1
    assert only["items"][0]["price"] == "1179.00"


def test_the_history_is_read_by_cursor(client):
    """An append-only feed read by offset repeats rows as new ones arrive."""
    token = admin_token(client)
    _, source = setup_source(client, token)
    body = {"external_id": "SKU-1", "market_code": "LV", "payload": FEED_ROW}
    for price in ("1179,00", "1099,00", "999,00"):
        ingest(client, token, source["id"], {**body, "payload": priced(FEED_ROW, price)})

    page = history(client, token, limit=2)
    assert [r["price"] for r in page["items"]] == ["999.00", "1099.00"]
    assert page["next_cursor"] is not None

    rest = history(client, token, limit=2, before_id=page["next_cursor"])
    assert [r["price"] for r in rest["items"]] == ["1179.00"]
    assert rest["next_cursor"] is None


def test_nothing_can_edit_or_delete_a_price(client):
    """A price that was charged was charged; a history that can be edited is not evidence."""
    token = admin_token(client)
    _, source = setup_source(client, token)
    ingest(
        client,
        token,
        source["id"],
        {"external_id": "SKU-1", "market_code": "LV", "payload": FEED_ROW},
    )
    row = history(client, token)["items"][0]

    for method in (client.patch, client.put, client.delete):
        response = method(f"/api/admin/price-history/{row['id']}", headers=auth(token))
        assert response.status_code in (404, 405)


def test_the_history_requires_an_admin_token(client):
    user_token = tokens(client, CUSTOMER)["access_token"]
    assert client.get("/api/admin/price-history", headers=auth(user_token)).status_code == 401
    assert client.get("/api/admin/price-history").status_code == 401


def test_re_reading_stored_bytes_can_extend_the_series(client):
    """A re-read that changes what we think the price was is a change like any other."""
    token = admin_token(client)
    _, source = setup_source(client, token)
    result = ingest(
        client,
        token,
        source["id"],
        {"external_id": "SKU-1", "market_code": "LV", "payload": FEED_ROW},
    )
    before = history(client, token)["total"]

    again = client.post(
        f"/api/admin/raw-offers/{result['raw_offer_id']}/renormalize", headers=auth(token)
    )
    assert again.status_code == 200
    # The same bytes read by the same ruleset give the same price, so nothing is added.
    assert history(client, token)["total"] == before


def test_setup_creates_no_rows_on_its_own(client):
    token = admin_token(client)
    setup_source(client, token)
    assert history(client, token)["total"] == 0
