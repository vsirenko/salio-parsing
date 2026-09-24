"""Ingestion: what a shop served, kept verbatim, and read."""

import pytest

from app.features.offers.normalization import content_hash, read
from tests.test_auth import ADMIN, CUSTOMER, auth, tokens

FEED_ROW = {
    "name": "Apple iPhone 15 Pro 256GB Natural Titanium",
    "vendor": "Apple",
    "categories": ["Elektronika", "Telefoni"],
    "ean": "194253-000001",
    "article": "MRXN3ZD/A",
    "price": "1 179,00",
    "currencyId": "eur",
    "available": "true",
    "params": [{"name": "Krāsa", "value": "Melns"}],
}


def admin_token(client) -> str:
    return tokens(client, ADMIN, panel="/admin")["access_token"]


def post(client, token, path, body, expect=201):
    response = client.post(path, headers=auth(token), json=body)
    assert response.status_code == expect, response.text
    return response.json()


def setup_source(client, token, *, marketplace=False):
    post(
        client,
        token,
        "/api/admin/markets",
        {"code": "LV", "name": "Latvia", "slug": "latvija", "languages": ["lv"]},
    )
    shop = post(
        client,
        token,
        "/api/admin/shops",
        {
            "slug": "rd",
            "name": "RD Electronics",
            "country_code": "LV",
            "is_marketplace": marketplace,
        },
    )
    source = post(
        client,
        token,
        f"/api/admin/shops/{shop['id']}/sources",
        {
            "slug": "rd-feed",
            "access": "wholesale",
            "decode": "xml",
            "delivers_full": ["catalogue", "price", "availability"],
            "trust": "high",
        },
    )
    return shop, source


def ingest(client, token, source_id, body, expect=202):
    response = client.post(f"/api/admin/sources/{source_id}/offers", headers=auth(token), json=body)
    assert response.status_code == expect, response.text
    return response.json()


# --- the ruleset, on its own ---


def test_a_feed_row_is_read():
    fields = read(FEED_ROW)
    assert fields["title"] == "Apple iPhone 15 Pro 256GB Natural Titanium"
    assert fields["brand_raw"] == "Apple"
    assert fields["category_raw"] == "Elektronika / Telefoni"
    # Punctuation out, digits kept.
    assert fields["gtin"] == "00194253000001"
    # A comma decimal separator and a space thousands separator are how feeds for humans
    # are written across the Baltics.
    assert str(fields["price"]) == "1179.00"
    assert fields["currency_code"] == "EUR"
    assert fields["availability"] == "in_stock"
    assert fields["attributes"] == {"Krāsa": "Melns"}


@pytest.mark.parametrize("value", ["n/a", "-", "", "12345", "0" * 20])
def test_a_barcode_that_is_not_one_is_refused(value):
    """A gtin field holding rubbish would put nonsense on the strongest signal there is."""
    assert read({"ean": value})["gtin"] is None


def test_the_hash_ignores_key_order():
    """A source that reorders its JSON has not changed its page."""
    assert content_hash({"b": 2, "a": 1}) == content_hash({"a": 1, "b": 2})
    assert content_hash({"a": 1}) != content_hash({"a": 2})


def test_currency_written_into_the_price():
    assert read({"price": "1179.00 EUR"})["currency_code"] == "EUR"


# --- ingestion ---


def test_one_observation_creates_the_listing_and_its_reading(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    result = ingest(
        client,
        token,
        source["id"],
        {"external_id": "SKU-1", "market_code": "LV", "payload": FEED_ROW},
    )
    assert result["offer_created"] is True
    assert result["stored"] is True

    offer = client.get(f"/api/admin/offers/{result['offer_id']}", headers=auth(token)).json()
    assert offer["price"] == "1179.00"
    assert offer["currency_code"] == "EUR"
    assert offer["availability"] == "in_stock"

    reading = client.get(
        f"/api/admin/raw-offers/{result['raw_offer_id']}/reading", headers=auth(token)
    ).json()
    assert reading["gtin"] == "00194253000001"
    assert reading["brand_raw"] == "Apple"
    # A brand string, not a brand: resolving it is matching's work.
    assert reading["brand_id"] is None


def test_an_unchanged_page_writes_nothing(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    body = {"external_id": "SKU-1", "market_code": "LV", "payload": FEED_ROW}

    first = ingest(client, token, source["id"], body)
    second = ingest(client, token, source["id"], body)

    assert first["stored"] is True
    assert second["stored"] is False
    assert second["offer_created"] is False
    assert second["raw_offer_id"] == first["raw_offer_id"]

    observations = client.get(
        f"/api/admin/offers/{first['offer_id']}/raw", headers=auth(token)
    ).json()
    assert len(observations) == 1


def test_a_changed_price_is_a_new_observation_of_the_same_listing(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    body = {"external_id": "SKU-1", "market_code": "LV", "payload": FEED_ROW}
    first = ingest(client, token, source["id"], body)

    cheaper = ingest(
        client,
        token,
        source["id"],
        {**body, "payload": {**FEED_ROW, "price": "999,00"}},
    )
    assert cheaper["offer_id"] == first["offer_id"]
    assert cheaper["raw_offer_id"] != first["raw_offer_id"]
    assert cheaper["stored"] is True

    observations = client.get(
        f"/api/admin/offers/{first['offer_id']}/raw", headers=auth(token)
    ).json()
    assert len(observations) == 2

    offer = client.get(f"/api/admin/offers/{first['offer_id']}", headers=auth(token)).json()
    assert offer["price"] == "999.00"


def test_two_channels_of_one_shop_converge_on_one_listing(client):
    """Hang the seller off the source instead and this becomes two offers, two price
    lines and two shops on a card."""
    token = admin_token(client)
    shop, feed = setup_source(client, token)
    scraper = post(
        client,
        token,
        f"/api/admin/shops/{shop['id']}/sources",
        {
            "slug": "rd-site",
            "access": "retail",
            "decode": "markup",
            "delivers_full": ["catalogue", "price", "availability"],
            "delivers_quick": ["price"],
            "trust": "low",
        },
    )

    body = {"external_id": "SKU-1", "market_code": "LV", "payload": FEED_ROW}
    from_feed = ingest(client, token, feed["id"], body)
    from_page = ingest(
        client,
        token,
        scraper["id"],
        {**body, "payload": {"title": "iPhone 15 Pro", "price": "1179"}},
    )

    assert from_page["offer_id"] == from_feed["offer_id"]
    observations = client.get(
        f"/api/admin/offers/{from_feed['offer_id']}/raw", headers=auth(token)
    ).json()
    # Two channels, two observations, one listing — and each remembers which saw it.
    assert {o["source_id"] for o in observations} == {feed["id"], scraper["id"]}


def test_a_marketplace_offer_has_to_name_its_seller(client):
    token = admin_token(client)
    _, source = setup_source(client, token, marketplace=True)
    refused = client.post(
        f"/api/admin/sources/{source['id']}/offers",
        headers=auth(token),
        json={"external_id": "SKU-1", "market_code": "LV", "payload": FEED_ROW},
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "seller_required"


def test_a_marketplace_trader_arrives_with_the_data(client):
    token = admin_token(client)
    shop, source = setup_source(client, token, marketplace=True)
    ingest(
        client,
        token,
        source["id"],
        {
            "external_id": "SKU-1",
            "market_code": "LV",
            "payload": FEED_ROW,
            "seller_external_id": "trader-42",
        },
    )
    sellers = client.get(f"/api/admin/shops/{shop['id']}/sellers", headers=auth(token)).json()
    assert [s["external_id"] for s in sellers] == ["trader-42"]


def test_two_traders_selling_the_same_sku_are_two_listings(client):
    token = admin_token(client)
    _, source = setup_source(client, token, marketplace=True)
    base = {"external_id": "SKU-1", "market_code": "LV", "payload": FEED_ROW}
    one = ingest(client, token, source["id"], {**base, "seller_external_id": "trader-1"})
    two = ingest(client, token, source["id"], {**base, "seller_external_id": "trader-2"})
    assert one["offer_id"] != two["offer_id"]


def test_an_unopened_market_is_refused(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    response = client.post(
        f"/api/admin/sources/{source['id']}/offers",
        headers=auth(token),
        json={"external_id": "SKU-1", "market_code": "EE", "payload": FEED_ROW},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_market"


# --- reading stored bytes again ---


def test_renormalizing_is_idempotent(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    result = ingest(
        client,
        token,
        source["id"],
        {"external_id": "SKU-1", "market_code": "LV", "payload": FEED_ROW},
    )

    again = client.post(
        f"/api/admin/raw-offers/{result['raw_offer_id']}/renormalize", headers=auth(token)
    )
    assert again.status_code == 200
    assert again.json()["id"] == result["normalized_offer_id"]
    assert again.json()["gtin"] == "00194253000001"


# --- the measurement everything is downstream of ---


def test_coverage_buckets_what_has_been_read(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    rows = {
        "with-barcode": FEED_ROW,
        "brand-and-part": {"name": "A thing", "brand": "Bosch", "article": "WAX28M42"},
        "brand-only": {"name": "A thing", "brand": "Bosch"},
        "nothing": {"name": "Some anonymous thing"},
    }
    for sku, payload in rows.items():
        ingest(
            client,
            token,
            source["id"],
            {"external_id": sku, "market_code": "LV", "payload": payload},
        )

    report = client.get("/api/admin/offers/coverage", headers=auth(token)).json()
    assert report["normalized_offers"] == 4
    assert report["with_gtin"] == 1
    assert report["with_brand_and_mpn"] == 1
    assert report["with_brand_only"] == 1
    assert report["with_nothing"] == 1
    assert report["gtin_share"] == 0.25
    # A barcode or a brand with a part number is what a deterministic matcher can use.
    assert report["deterministic_share"] == 0.5


def test_coverage_of_nothing(client):
    token = admin_token(client)
    report = client.get("/api/admin/offers/coverage", headers=auth(token)).json()
    assert report["normalized_offers"] == 0
    assert report["deterministic_share"] == 0.0


# --- guards ---


def test_offers_require_an_admin_token(client):
    user_token = tokens(client, CUSTOMER)["access_token"]
    assert client.get("/api/admin/offers", headers=auth(user_token)).status_code == 401
    assert client.post("/api/admin/sources/1/offers", json={}).status_code == 401


# --- the path of one listing ---


def test_a_trace_watches_and_decides_nothing():
    """The same reading with a trace as without, and each step says what it changed."""
    steps: list[dict] = []
    traced = read(FEED_ROW, trace=steps)
    assert traced == read(FEED_ROW)
    assert steps[0]["rule"] == "generic"
    assert steps[0]["changed"]["gtin"] == [None, "00194253000001"]
    assert all({"rule", "layer", "round", "why", "changed"} <= set(step) for step in steps)


def test_a_listing_can_be_traced_from_its_bytes_to_its_reading(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    result = ingest(
        client,
        token,
        source["id"],
        {"external_id": "SKU-1", "market_code": "LV", "payload": FEED_ROW},
    )
    trace = client.get(f"/api/admin/offers/{result['offer_id']}/trace", headers=auth(token))
    assert trace.status_code == 200, trace.text
    body = trace.json()
    assert body["observation"]["payload"]["ean"] == FEED_ROW["ean"]
    assert body["now"]["fields"]["gtin"] == "00194253000001"
    # Nothing changed since it was read, so what is stored is what would be read now.
    assert body["stale"] is False
    assert body["steps"][0]["rule"] == "generic"
    # Not matched yet: no entry, no history.
    assert (body["match"], body["entry"], body["history"]) == (None, None, [])


def test_a_trace_of_nothing_is_a_404(client):
    token = admin_token(client)
    assert client.get("/api/admin/offers/999999/trace", headers=auth(token)).status_code == 404
