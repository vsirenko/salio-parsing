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
