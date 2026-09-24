"""A shop row with its counts and the health of its collection; a channel, a seller, a group."""

from datetime import UTC, datetime, timedelta

from tests.test_auth import auth
from tests.test_catalog import admin_token, post
from tests.test_offer_list import an_entry_with_listings


def a_run(event_loop, source_id: int, status: str, minutes_ago: int, kind: str = "full") -> None:
    """A pass that began before the listings were last seen, so they stay on sale."""
    from app.db.models import Run
    from app.db.session import session_factory

    async def run() -> None:
        async with session_factory() as session:
            at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
            session.add(
                Run(source_id=source_id, kind=kind, status=status, started_at=at, finished_at=at)
            )
            await session.commit()

    event_loop.run_until_complete(run())


def a_running_shop(client, token):
    """The shop behind three placed listings, with its channel switched on and scheduled."""
    source, *_ = an_entry_with_listings(client, token)
    client.patch(
        f"/api/admin/sources/{source['id']}",
        headers=auth(token),
        json={"is_enabled": True, "cron_full": "0 3 * * *"},
    )
    return source


def shop_row(client, token, shop_id, **params):
    rows = client.get("/api/admin/shops", headers=auth(token), params=params).json()["items"]
    return next((row for row in rows if row["id"] == shop_id), None)


def test_a_shop_row_counts_what_it_holds(client):
    token = admin_token(client)
    source = a_running_shop(client, token)
    shop = client.get(f"/api/admin/shops/{source['shop_id']}", headers=auth(token)).json()
    assert (shop["sources_count"], shop["sellers_count"]) == (1, 1)
    assert (shop["offers_count"], shop["products_count"]) == (3, 1)
    assert shop["group"] is None
    assert shop["logo_url"] is None
    assert isinstance(shop["markets"], list)

    other = post(
        client,
        token,
        "/api/admin/shops",
        {"slug": "empty", "name": "Empty", "country_code": "LV", "logo_url": "https://e/l.png"},
    )
    assert other["logo_url"] == "https://e/l.png"
    # A second shop counts its own listings, not every shop's.
    assert shop_row(client, token, other["id"])["offers_count"] == 0
    rows = client.get(
        "/api/admin/shops", headers=auth(token), params={"sort": "-offers_count"}
    ).json()["items"]
    assert [row["id"] for row in rows] == [shop["id"], other["id"]]
    found = client.get("/api/admin/shops", headers=auth(token), params={"search": "empt"})
    assert [row["id"] for row in found.json()["items"]] == [other["id"]]
    bad = client.get("/api/admin/shops", headers=auth(token), params={"sort": "rating"})
    assert bad.status_code == 422


def test_health_follows_the_newest_full_pass_of_each_enabled_channel(client, event_loop):
    token = admin_token(client)
    source = a_running_shop(client, token)
    shop_id = source["shop_id"]

    health = shop_row(client, token, shop_id)["health"]
    assert health["status"] == "never"
    assert (health["enabled_sources"], health["failing_sources"]) == (1, 0)

    a_run(event_loop, source["id"], "ok", minutes_ago=60)
    health = shop_row(client, token, shop_id, health="ok")["health"]
    assert health["last_full_ok_at"] is not None

    # A quick pass breaking says nothing about the catalogue.
    a_run(event_loop, source["id"], "failed", minutes_ago=40, kind="quick")
    assert shop_row(client, token, shop_id)["health"]["status"] == "ok"

    a_run(event_loop, source["id"], "failed", minutes_ago=30)
    row = shop_row(client, token, shop_id, health="failing")
    assert (row["health"]["status"], row["health"]["failing_sources"]) == ("failing", 1)
    # The last good pass is still the one it had.
    assert row["health"]["last_full_ok_at"] == health["last_full_ok_at"]
    assert shop_row(client, token, shop_id, health="ok") is None


def test_a_channel_says_how_it_ran_and_when_it_runs_next(client, event_loop):
    token = admin_token(client)
    source = a_running_shop(client, token)
    a_run(event_loop, source["id"], "ok", minutes_ago=60)
    a_run(event_loop, source["id"], "failed", minutes_ago=30)

    one = client.get(f"/api/admin/sources/{source['id']}", headers=auth(token)).json()
    assert one["last_run"]["status"] == "failed"
    assert one["last_full_ok_at"] is not None
    assert one["next_full_at"] is not None and one["next_quick_at"] is None
    assert one["offers_count"] == 3
    listed = client.get(f"/api/admin/shops/{source['shop_id']}/sources", headers=auth(token))
    assert listed.json() == [one]

    off = client.patch(
        f"/api/admin/sources/{source['id']}", headers=auth(token), json={"is_enabled": False}
    ).json()
    assert off["next_full_at"] is None


def test_a_channel_with_history_is_disabled_not_deleted(client, event_loop):
    token = admin_token(client)
    source = a_running_shop(client, token)
    kept = client.delete(f"/api/admin/sources/{source['id']}", headers=auth(token))
    assert kept.status_code == 409
    assert kept.json()["error"]["code"] == "source_has_history"

    spare = post(
        client,
        token,
        f"/api/admin/shops/{source['shop_id']}/sources",
        {"slug": "by-mistake", "access": "retail", "decode": "markup", "delivers_full": ["price"]},
    )
    gone = client.delete(f"/api/admin/sources/{spare['id']}", headers=auth(token))
    assert gone.status_code == 204
    missing = client.get(f"/api/admin/sources/{spare['id']}", headers=auth(token))
    assert missing.status_code == 404


def test_a_seller_counts_its_listings_and_can_be_renamed(client):
    token = admin_token(client)
    source = a_running_shop(client, token)
    [seller] = client.get(
        f"/api/admin/shops/{source['shop_id']}/sellers", headers=auth(token)
    ).json()
    assert seller["offers_count"] == 3
    renamed = client.patch(
        f"/api/admin/sellers/{seller['id']}", headers=auth(token), json={"name": "RD"}
    )
    assert renamed.status_code == 200, renamed.text
    assert (renamed.json()["name"], renamed.json()["offers_count"]) == ("RD", 3)
    assert (
        client.patch(
            "/api/admin/sellers/999999", headers=auth(token), json={"name": "x"}
        ).status_code
        == 404
    )


def test_a_group_is_read_and_edited_one_at_a_time(client):
    token = admin_token(client)
    group = post(client, token, "/api/admin/shop-groups", {"slug": "mm", "name": "MediaMarkt"})
    assert group["shops_count"] == 0
    post(
        client,
        token,
        "/api/admin/shops",
        {"slug": "mm-lv", "name": "MM LV", "country_code": "LV", "shop_group_id": group["id"]},
    )
    one = client.get(f"/api/admin/shop-groups/{group['id']}", headers=auth(token)).json()
    assert one["shops_count"] == 1
    edited = client.patch(
        f"/api/admin/shop-groups/{group['id']}", headers=auth(token), json={"name": "Media Markt"}
    ).json()
    assert (edited["name"], edited["slug"], edited["shops_count"]) == ("Media Markt", "mm", 1)
    shop = client.get("/api/admin/shops", headers=auth(token)).json()["items"][0]
    assert shop["group"] == {"id": group["id"], "name": "Media Markt"}
