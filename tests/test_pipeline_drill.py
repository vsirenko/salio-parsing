"""From a pipeline node to the listings behind it, and the pipeline kept day by day."""

from datetime import UTC, datetime

from tests.test_auth import auth
from tests.test_matching import admin_token, offer_from
from tests.test_offer_list import an_entry_with_listings


def a_listing_without_a_barcode_or_capacity(client, token, source):
    return offer_from(
        client,
        token,
        source["id"],
        {"name": "Apple iPhone 15", "brand": "Apple", "model": "iPhone 15", "price": "700"},
        external_id="B-1",
    )


def offer_ids(client, token, **params):
    response = client.get("/api/admin/offers", headers=auth(token), params=params)
    assert response.status_code == 200, response.text
    return sorted(row["id"] for row in response.json()["items"])


def test_the_offer_list_filters_by_what_a_reading_found(client):
    token = admin_token(client)
    source, _, first, second, worn = an_entry_with_listings(client, token)
    bare = a_listing_without_a_barcode_or_capacity(client, token, source)
    full = sorted([first, second, worn])

    assert offer_ids(client, token, source_id=source["id"]) == sorted([*full, bare])
    assert offer_ids(client, token, source_id=999999) == []
    assert offer_ids(client, token, has_gtin=True) == full
    assert offer_ids(client, token, has_gtin=False) == [bare]
    assert offer_ids(client, token, has_model=True) == sorted([*full, bare])
    assert offer_ids(client, token, has_model=False) == []
    assert offer_ids(client, token, has_all_axes=True) == full
    assert offer_ids(client, token, has_all_axes=False) == [bare]
    assert offer_ids(client, token, missing_axis="storage_mb") == [bare]
    # An axis no category here requires is missing from nothing.
    assert offer_ids(client, token, missing_axis="color") == []


def test_the_read_node_names_the_axes_that_are_missing(client):
    token = admin_token(client)
    source, *_ = an_entry_with_listings(client, token)
    a_listing_without_a_barcode_or_capacity(client, token, source)

    body = client.get("/api/admin/pipeline", headers=auth(token)).json()
    read = next(stage for stage in body["stages"] if stage["key"] == "read")
    assert read["missing_axes"] == {"storage_mb": 1}
    assert (read["count"], read["parts"]["all_axes"]) == (4, 3)
    [flow] = body["sources"]
    assert flow["missing_axes"] == {"storage_mb": 1}
    assert flow["shop_id"] and flow["category_id"]
    assert flow["category_slug"] == flow["category"] == "phones"
    assert flow["category_name"] == "Phones"
    assert flow["last_run_id"] is None


def test_a_channel_row_links_its_last_full_run(client):
    from tests.test_runs import finish, start

    token = admin_token(client)
    source, *_ = an_entry_with_listings(client, token)
    run = start(client, token, source["id"])
    done = finish(client, token, run["id"], items_seen=3, items_ingested=3)
    [flow] = client.get("/api/admin/pipeline", headers=auth(token)).json()["sources"]
    assert flow["last_run_id"] == run["id"]
    assert flow["last_run_status"] == done["status"]


def test_the_day_is_kept_once_and_read_back(client, event_loop):
    from app.db.session import session_factory
    from app.features.pipeline.service import PipelineService
    from app.features.runs.scheduler import Scheduler

    token = admin_token(client)
    source, *_ = an_entry_with_listings(client, token)
    a_listing_without_a_barcode_or_capacity(client, token, source)
    today = datetime.now(UTC).date()

    async def keep() -> int:
        async with session_factory() as session:
            written = await PipelineService(session).take_snapshot(today)
            await session.commit()
            return written

    # Everything, and each category.
    assert event_loop.run_until_complete(keep()) == 2
    assert event_loop.run_until_complete(keep()) == 0
    # The scheduler's own hook finds the day kept and writes nothing more.
    event_loop.run_until_complete(Scheduler().keep_the_day())

    [day] = client.get("/api/admin/pipeline/history", headers=auth(token)).json()
    assert (day["day"], day["scope"]) == (today.isoformat(), "all")
    assert (day["listed"], day["read"], day["all_axes"]) == (4, 4, 3)
    assert day["missing_axes"] == {"storage_mb": 1}
    assert day["placed"] == 3 and day["placed_by_method"] == {"gtin": 3}
    phones = client.get(
        "/api/admin/pipeline/history", headers=auth(token), params={"scope": "phones"}
    ).json()
    assert [row["scope"] for row in phones] == ["phones"]


def test_re_reading_an_older_observation_leaves_the_newer_one_on_the_listing(client):
    """The listing carries the newest observation's reading, the one the matcher and the
    pipeline read by — not whichever was read last."""
    token = admin_token(client)
    source, *_ = an_entry_with_listings(client, token)
    body = {"brand": "Apple", "model": "iPhone 15", "price": "700"}
    offer = offer_from(
        client, token, source["id"], {**body, "name": "Old title"}, external_id="R-1"
    )
    offer_from(client, token, source["id"], {**body, "name": "New title"}, external_id="R-1")
    raws = client.get(f"/api/admin/offers/{offer}/raw", headers=auth(token)).json()
    older = min(raws, key=lambda raw: raw["id"])
    re_read = client.post(f"/api/admin/raw-offers/{older['id']}/renormalize", headers=auth(token))
    assert re_read.status_code == 200, re_read.text
    row = client.get(f"/api/admin/offers/{offer}", headers=auth(token)).json()
    assert row["title"] == "New title"
