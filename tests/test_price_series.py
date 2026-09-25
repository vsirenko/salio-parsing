"""A price chart's data: a band across the market and a line per shop, day by day."""

from tests.test_auth import auth
from tests.test_matching import (
    a_shop_we_can_build_from,
    a_storage_axis,
    admin_token,
    ingest,
    offer_from,
    promote,
)


def series(client, token, expect=200, **params):
    response = client.get("/api/admin/price-history/series", headers=auth(token), params=params)
    assert response.status_code == expect, response.text
    return response.json()


def listing(client, token, source, external_id, price, availability=None):
    payload = {
        "name": "Apple iPhone 15 256 GB",
        "brand": "Apple",
        "model": "iPhone 15",
        "ean": "4006381333931",
        "price": price,
        "currency": "EUR",
        "attributes": {"storage": "256 GB"},
    }
    if availability:
        payload["availability"] = availability
    return offer_from(client, token, source["id"], payload, external_id=external_id)


def test_a_day_is_the_band_of_the_listings_on_sale_and_a_line_per_shop(client):
    token = admin_token(client)
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])
    first = listing(client, token, source, "S-1", "799.00")
    variant_id = promote(client, token, first)["variant_id"]
    second = listing(client, token, source, "S-2", "749.00")
    client.post(f"/api/admin/offers/{second}/match", headers=auth(token))
    # A price that moved: the day carries the newest one.
    ingest(
        client,
        token,
        source["id"],
        {
            "external_id": "S-1",
            "market_code": "LV",
            "payload": {
                "name": "Apple iPhone 15 256 GB",
                "brand": "Apple",
                "model": "iPhone 15",
                "ean": "4006381333931",
                "price": "779.00",
                "currency": "EUR",
                "attributes": {"storage": "256 GB"},
            },
        },
    )

    body = series(client, token, variant_id=variant_id, days=7)
    [today] = body["days"]
    assert (today["min"], today["max"], today["listings"]) == ("749.00", "779.00", 2)
    assert today["median"] == "764.00"
    assert body["currency_code"] == "EUR"
    [shop] = body["shops"]
    assert shop["points"][-1]["price"] == "749.00"

    variant = client.get(f"/api/admin/variants/{variant_id}", headers=auth(token)).json()
    family = series(client, token, product_id=variant["product"]["id"], days=7)
    assert family["days"] == body["days"]


def test_a_listing_the_shop_has_none_of_is_left_out_unless_asked_for(client):
    token = admin_token(client)
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])
    first = listing(client, token, source, "S-1", "799.00")
    variant_id = promote(client, token, first)["variant_id"]
    gone = listing(client, token, source, "S-2", "599.00", availability="out_of_stock")
    client.post(f"/api/admin/offers/{gone}/match", headers=auth(token))

    [day] = series(client, token, variant_id=variant_id)["days"]
    assert (day["min"], day["listings"]) == ("799.00", 1)
    [day] = series(client, token, variant_id=variant_id, with_out_of_stock=True)["days"]
    assert (day["min"], day["listings"]) == ("599.00", 2)


def test_a_series_names_exactly_one_thing_that_exists(client):
    token = admin_token(client)
    assert series(client, token, expect=422)["error"]["code"] == "one_scope"
    series(client, token, expect=422, variant_id=1, product_id=1)
    series(client, token, expect=404, variant_id=999999)
    series(client, token, expect=404, product_id=999999)
