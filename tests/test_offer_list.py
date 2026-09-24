"""Who sells a thing: listings by entry or family, named, and only what is on sale new."""

from datetime import UTC, datetime, timedelta

from tests.test_auth import auth
from tests.test_catalog import admin_token
from tests.test_matching import a_shop_we_can_build_from, a_storage_axis, offer_from, promote


def an_entry_with_listings(client, token):
    """One entry, placed by barcode: a new listing, a refurbished one, and a second new one."""
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])
    listing = {
        "name": "Apple iPhone 15 256 GB",
        "brand": "Apple",
        "model": "iPhone 15",
        "ean": "4006381333931",
        "price": "799.00",
        "attributes": {"storage": "256 GB"},
    }
    first = offer_from(client, token, source["id"], listing, external_id="A-1")
    variant_id = promote(client, token, first)["variant_id"]
    second = offer_from(
        client, token, source["id"], {**listing, "price": "749.00"}, external_id="A-2"
    )
    worn = offer_from(
        client, token, source["id"], {**listing, "price": "499.00"}, external_id="A-3"
    )
    for offer_id in (second, worn):
        client.post(f"/api/admin/offers/{offer_id}/match", headers=auth(token))
    return source, variant_id, first, second, worn


def mark_refurbished(event_loop, offer_id: int) -> None:
    from sqlalchemy import update

    from app.db.models import Offer
    from app.db.session import session_factory

    async def mark() -> None:
        async with session_factory() as session:
            await session.execute(
                update(Offer).where(Offer.id == offer_id).values(condition="refurbished")
            )
            await session.commit()

    event_loop.run_until_complete(mark())


def a_full_pass_after_now(event_loop, source_id: int) -> None:
    """A full pass that ended ok and began after every listing was last seen."""
    from app.db.models import Run
    from app.db.session import session_factory

    async def run() -> None:
        async with session_factory() as session:
            later = datetime.now(UTC) + timedelta(minutes=5)
            session.add(
                Run(
                    source_id=source_id,
                    kind="full",
                    status="ok",
                    started_at=later,
                    finished_at=later,
                )
            )
            await session.commit()

    event_loop.run_until_complete(run())


def test_the_listings_of_an_entry_name_their_shop_and_where_they_are_placed(client, event_loop):
    token = admin_token(client)
    _, variant_id, first, second, worn = an_entry_with_listings(client, token)
    mark_refurbished(event_loop, worn)

    page = client.get(
        "/api/admin/offers",
        headers=auth(token),
        params={"variant_id": variant_id, "condition": "new", "listed": "true", "sort": "price"},
    ).json()
    assert [row["id"] for row in page["items"]] == [second, first]
    row = page["items"][0]
    assert row["shop"]["name"] == "RD Electronics"
    assert row["placed_on"]["variant_id"] == variant_id
    assert row["placed_on"]["method"] == "gtin"
    assert row["listed"] is True


def test_a_family_and_an_entry_count_only_new_listings_on_sale(client, event_loop):
    token = admin_token(client)
    source, variant_id, first, second, worn = an_entry_with_listings(client, token)
    mark_refurbished(event_loop, worn)

    variant = client.get(f"/api/admin/variants/{variant_id}", headers=auth(token)).json()
    assert (variant["offers_count"], variant["shops_count"], variant["min_price"]) == (
        2,
        1,
        "749.00",
    )
    assert variant["axes"] == {"storage_mb": 262144}
    assert variant["product"]["title"]
    family = client.get(
        f"/api/admin/products/{variant['product']['id']}", headers=auth(token)
    ).json()
    assert (family["offers_count"], family["min_price"]) == (2, "749.00")

    # The shop has since finished a full pass that saw none of them: nothing is on sale.
    a_full_pass_after_now(event_loop, source["id"])
    variant = client.get(f"/api/admin/variants/{variant_id}", headers=auth(token)).json()
    assert (variant["offers_count"], variant["min_price"]) == (0, None)
    gone = client.get(
        "/api/admin/offers",
        headers=auth(token),
        params={"product_id": variant["product"]["id"], "listed": "false"},
    ).json()
    assert {row["id"] for row in gone["items"]} == {first, second, worn}


def test_entries_sort_and_search_like_families(client):
    token = admin_token(client)
    _, variant_id, *_ = an_entry_with_listings(client, token)
    found = client.get(
        "/api/admin/variants", headers=auth(token), params={"search": "4006381333931"}
    ).json()
    assert [row["id"] for row in found["items"]] == [variant_id]
    refused = client.get("/api/admin/variants", headers=auth(token), params={"sort": "colour"})
    assert refused.status_code == 422
    listed = client.get("/api/admin/variants", headers=auth(token), params={"sort": "-min_price"})
    assert listed.status_code == 200


# --- the list a person reviews placements from ---


def a_quick_run(event_loop, source_id: int) -> int:
    from app.db.models import Run
    from app.db.session import session_factory

    async def run() -> int:
        async with session_factory() as session:
            quick = Run(source_id=source_id, kind="quick", status="running")
            session.add(quick)
            await session.commit()
            return quick.id

    return event_loop.run_until_complete(run())


def a_review_list(client, token):
    """Three placed listings, one the matcher queued, one nobody has tried to place."""
    source, variant_id, first, second, worn = an_entry_with_listings(client, token)
    stranger = offer_from(
        client,
        token,
        source["id"],
        {"name": "Nokia 3310 dual SIM", "brand": "Nokia", "price": "59.00"},
        external_id="N-1",
    )
    client.post(f"/api/admin/offers/{stranger}/match", headers=auth(token))
    untried = offer_from(
        client,
        token,
        source["id"],
        {"name": "Zzz charger", "price": "9.00", "availability": "out of stock"},
        external_id="Z-1",
    )
    return source, variant_id, (first, second, worn), stranger, untried


def offer_ids(client, token, **params):
    response = client.get("/api/admin/offers", headers=auth(token), params=params)
    assert response.status_code == 200, response.text
    return [row["id"] for row in response.json()["items"]]


def test_a_listing_row_says_what_the_shop_called_it_and_where_the_matcher_left_it(client):
    token = admin_token(client)
    source, variant_id, placed, stranger, untried = a_review_list(client, token)
    rows = {
        row["id"]: row
        for row in client.get("/api/admin/offers", headers=auth(token)).json()["items"]
    }
    one = rows[placed[1]]
    assert (one["title"], one["brand_raw"], one["gtin"]) == (
        "Apple iPhone 15 256 GB",
        "Apple",
        "04006381333931",
    )
    assert one["brand"]["name"] == "Apple"
    assert one["category"]["name"] == "Phones"
    assert (one["match_state"], one["queue_reason"]) == ("placed", None)

    queued = rows[stranger]
    assert (queued["match_state"], queued["queue_reason"]) == ("queued", "brand_unknown")
    # Not placed, so no brand of ours — but what its channel collects is known.
    assert queued["brand"] is None and queued["brand_raw"] == "Nokia"
    assert queued["category"]["name"] == "Phones"
    assert rows[untried]["match_state"] == "unplaced"
    assert rows[untried]["title"] == "Zzz charger"


def test_the_review_filters(client):
    token = admin_token(client)
    source, variant_id, placed, stranger, untried = a_review_list(client, token)
    brand_id = client.get(f"/api/admin/offers/{placed[0]}", headers=auth(token)).json()["brand"][
        "id"
    ]

    assert offer_ids(client, token, match_state="queued") == [stranger]
    assert sorted(offer_ids(client, token, match_state=["queued", "unplaced"])) == [
        stranger,
        untried,
    ]
    assert offer_ids(client, token, queue_reason="brand_unknown") == [stranger]
    assert offer_ids(client, token, queue_reason="ambiguous") == []
    assert sorted(offer_ids(client, token, method="gtin")) == sorted(placed)
    assert offer_ids(client, token, method="brand_model") == []
    assert sorted(offer_ids(client, token, brand_id=brand_id)) == sorted(placed)
    assert offer_ids(client, token, availability="out_of_stock") == [untried]
    assert sorted(offer_ids(client, token, price_min="100", price_max="750")) == sorted(placed[1:])
    assert offer_ids(client, token, search="nokia") == [stranger]
    assert offer_ids(client, token, search="Z-1") == [untried]
    assert sorted(offer_ids(client, token, search="4006381333931")) == sorted(placed)
    # A barcode is equal or not: a fragment of one names nothing.
    assert offer_ids(client, token, search="40063813") == []
    everything = offer_ids(client, token, sort="title")
    assert everything[:3] == sorted(placed) and everything[3:] == [stranger, untried]
    bad = client.get("/api/admin/offers", headers=auth(token), params={"match_state": "maybe"})
    assert bad.status_code == 422


def test_a_quick_pass_does_not_blank_the_name(client, event_loop):
    token = admin_token(client)
    source, _, placed, *_ = a_review_list(client, token)
    run_id = a_quick_run(event_loop, source["id"])
    response = client.post(
        f"/api/admin/sources/{source['id']}/offers/batch",
        headers=auth(token),
        json={
            "market_code": "LV",
            "run_id": run_id,
            "offers": [{"external_id": "A-2", "payload": {"price": "699.00"}}],
        },
    )
    assert response.status_code == 202, response.text
    row = client.get(f"/api/admin/offers/{placed[1]}", headers=auth(token)).json()
    assert row["price"] == "699.00"
    assert (row["title"], row["gtin"]) == ("Apple iPhone 15 256 GB", "04006381333931")
