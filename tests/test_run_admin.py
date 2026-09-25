"""Runs as a panel reads them: named, filtered, cancelled, and saying what did not make it."""

from datetime import UTC, datetime, timedelta

from tests.test_auth import auth
from tests.test_matching import admin_token
from tests.test_runs import channel, finish, start
from tests.test_worker import taken, worker_token


def runs(client, token, **params):
    response = client.get("/api/admin/runs", headers=auth(token), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_a_run_row_names_its_channel_shop_and_category(client):
    token = admin_token(client)
    source = channel(client, token, cron_full=None, cron_quick=None)
    run = start(client, token, source["id"])
    assert run["source"] == {"id": source["id"], "slug": source["slug"]}
    assert run["shop"]["id"] == source["shop_id"] and run["shop"]["name"]
    assert run["duration_seconds"] is None
    assert run["contract"] == {"verdict": None, "checks": []}

    done = finish(client, token, run["id"], items_seen=3, items_ingested=3)
    assert done["duration_seconds"] is not None
    assert all(set(check) >= {"name", "passed"} for check in done["contract"]["checks"])
    assert done["contract"]["checks"]
    [row] = runs(client, token)["items"]
    assert row["source"]["slug"] == source["slug"]


def test_runs_filter_and_sort(client):
    token = admin_token(client)
    source = channel(client, token, cron_full=None, cron_quick=None)
    full = start(client, token, source["id"])
    finish(client, token, full["id"], items_seen=900, items_ingested=900)
    quick = start(client, token, source["id"], kind="quick")

    assert [r["id"] for r in runs(client, token, kind="quick")["items"]] == [quick["id"]]
    assert runs(client, token, kind=["quick", "full"])["total"] == 2
    assert [r["id"] for r in runs(client, token, status="queued")["items"]] == [quick["id"]]
    assert runs(client, token, status=["ok", "rejected", "queued"])["total"] == 2
    assert runs(client, token, source_id=source["id"])["total"] == 2
    assert runs(client, token, shop_id=source["shop_id"])["total"] == 2
    assert runs(client, token, shop_id=999999)["total"] == 0
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert runs(client, token, started_from=future)["total"] == 0
    assert runs(client, token, started_to=future)["total"] == 2
    assert runs(client, token, sort="-items_seen")["items"][0]["id"] == full["id"]
    # A live run has no length yet and sorts as the longest.
    assert runs(client, token, sort="-duration")["items"][0]["id"] == quick["id"]
    bad = client.get("/api/admin/runs", headers=auth(token), params={"sort": "kind"})
    assert bad.status_code == 422


def test_a_queued_run_is_cancelled_and_its_slot_freed(client):
    token = admin_token(client)
    source = channel(client, token, cron_full=None, cron_quick=None)
    run = start(client, token, source["id"])
    # One live run per channel and kind.
    start(client, token, source["id"], expect=409)

    cancelled = client.post(f"/api/admin/runs/{run['id']}/cancel", headers=auth(token))
    assert cancelled.status_code == 200, cancelled.text
    body = cancelled.json()
    assert (body["status"], body["contract"]["verdict"]) == ("cancelled", "not_evaluated")
    assert body["finished_at"] is not None
    start(client, token, source["id"])
    again = client.post(f"/api/admin/runs/{run['id']}/cancel", headers=auth(token))
    assert (again.status_code, again.json()["error"]["code"]) == (409, "run_finished")


def test_a_running_run_cancelled_refuses_what_its_worker_still_sends(client, event_loop):
    from app.db.session import session_factory
    from app.features.runs.service import RunService

    token = admin_token(client)
    source = channel(client, token, cron_full=None, cron_quick=None)
    run = start(client, token, source["id"])
    taken(event_loop, run["id"])
    client.post(f"/api/admin/runs/{run['id']}/cancel", headers=auth(token))

    worker = worker_token(client)
    handed = client.post(
        f"/api/worker/sources/{source['id']}/offers/batch",
        headers=auth(worker),
        json={
            "market_code": "LV",
            "run_id": run["id"],
            "offers": [{"external_id": "W-1", "payload": {"name": "Thing"}}],
        },
    )
    assert (handed.status_code, handed.json()["error"]["code"]) == (409, "run_cancelled")
    finished = client.post(
        f"/api/worker/runs/{run['id']}/finish",
        headers=auth(worker),
        json={"items_seen": 1, "items_ingested": 1},
    )
    assert finished.status_code == 409

    async def which() -> set[int]:
        async with session_factory() as session:
            return await RunService(session).cancelled_among([run["id"]])

    # What the scheduler asks of the workers it holds, to kill this one.
    assert event_loop.run_until_complete(which()) == {run["id"]}


def test_a_run_keeps_a_sample_of_what_did_not_make_it(client, event_loop):
    token = admin_token(client)
    source = channel(client, token, cron_full=None, cron_quick=None)
    run = start(client, token, source["id"])
    taken(event_loop, run["id"])
    worker = worker_token(client)
    reported = client.post(
        f"/api/worker/runs/{run['id']}/finish",
        headers=auth(worker),
        json={
            "items_seen": 3,
            "items_ingested": 1,
            "items_failed": 2,
            "failures": [
                {
                    "stage": "parse",
                    "external_id": "A-2",
                    "url": "https://s/a2",
                    "error": "no price",
                },
                {"stage": "fetch", "external_id": "A-3", "error": "HTTPStatusError: 503"},
            ],
        },
    )
    assert reported.status_code == 200, reported.text

    sample = client.get(f"/api/admin/runs/{run['id']}/failures", headers=auth(token)).json()
    assert (sample["items_failed"], sample["sampled"]) == (2, 2)
    assert [item["stage"] for item in sample["items"]] == ["parse", "fetch"]
    assert sample["items"][0]["url"] == "https://s/a2"
    one = client.get(
        f"/api/admin/runs/{run['id']}/failures", headers=auth(token), params={"limit": 1}
    ).json()
    assert (one["sampled"], len(one["items"])) == (2, 1)


def test_the_worker_names_the_products_that_failed(client, event_loop, tmp_path):
    from app.features.runs.schemas import Job, Kind
    from app.features.runs.snapshots import SnapshotStore
    from app.features.runs.worker import Failures, _read_all
    from tests.test_worker import a_slow_shop

    channel_ = a_slow_shop(5, in_flight=[])
    broken = channel_.parse

    def parse(snapshot):
        if snapshot.external_id == "3":
            raise ValueError("this card is nonsense")
        return broken(snapshot)

    channel_.parse = parse
    job = Job(
        run_id=1,
        source_id=1,
        source_slug="slow-shop",
        kind=Kind.FULL,
        access="retail",
        decode="markup",
        base_url=None,
        market_codes=["LV"],
        delivers=["catalogue", "price"],
    )
    listings = event_loop.run_until_complete(channel_.discover(None, job))
    failures = Failures()
    _, failed = event_loop.run_until_complete(
        _read_all(job, channel_, None, SnapshotStore(tmp_path), listings, failures)
    )
    assert failed == 1
    [failure] = failures.items
    assert (failure.stage, failure.external_id) == ("parse", "3")
    assert failure.error == "ValueError: this card is nonsense"


# --- reading a category's or a brand's channels again ---


def reparse(client, token, expect=202, **body):
    response = client.post("/api/admin/runs/reparse", headers=auth(token), json=body)
    assert response.status_code == expect, response.text
    return response.json()


def test_a_category_s_channels_are_read_again_at_once(client):
    from tests.test_matching import a_shop_we_can_build_from, offer_from

    token = admin_token(client)
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    offer_from(client, token, source["id"], {"name": "Apple iPhone 15", "brand": "Apple"})

    report = reparse(client, token, category_id=category["id"])
    [queued] = report["queued"]
    assert queued["source"] == {"id": source["id"], "slug": source["slug"]}
    run = client.get(f"/api/admin/runs/{queued['run_id']}", headers=auth(token)).json()
    assert (run["kind"], run["status"]) == ("reparse", "queued")

    # Asked again while that one is still going: nothing new, and it says which.
    again = reparse(client, token, category_id=category["id"])
    assert (again["queued"], again["already_going"]) == ([], [queued["source"]])


def test_a_brand_narrows_it_to_the_channels_that_have_read_it(client):
    from tests.test_matching import a_shop_we_can_build_from, offer_from, run_on

    token = admin_token(client)
    _, source, category, brand = a_shop_we_can_build_from(client, token)
    assert reparse(client, token, brand_id=brand["id"])["queued"] == []

    offer = offer_from(client, token, source["id"], {"name": "Apple iPhone 15", "brand": "Apple"})
    # Unplaced, it waits in the queue under the maker the matcher resolved.
    assert run_on(client, token, offer)["matched"] is False
    [queued] = reparse(client, token, brand_id=brand["id"], category_id=category["id"])["queued"]
    assert queued["source"]["id"] == source["id"]


def test_a_reparse_names_something_that_exists(client):
    token = admin_token(client)
    reparse(client, token, expect=422)
    assert reparse(client, token, expect=404, category_id=999999)["error"]["code"]
    reparse(client, token, expect=404, brand_id=999999)


def test_a_channel_off_the_schedule_is_read_again_and_one_that_collected_nothing_is_not(client):
    from tests.test_matching import a_shop_we_can_build_from, offer_from

    token = admin_token(client)
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    assert reparse(client, token, category_id=category["id"])["queued"] == []
    offer_from(client, token, source["id"], {"name": "Apple iPhone 15", "brand": "Apple"})
    assert source["is_enabled"] is False
    [queued] = reparse(client, token, category_id=category["id"])["queued"]
    assert queued["source"]["id"] == source["id"]


def test_a_reparse_rereads_the_newest_observation_too(client, event_loop):
    """The snapshot a reparse re-reads may be an older observation than the one the listing
    shows; three onea iPads kept an old model through a full reparse that way."""
    from sqlalchemy import func, select

    from app.db.models import NormalizedOffer
    from app.db.session import session_factory

    token = admin_token(client)
    source = channel(client, token, cron_full=None, cron_quick=None)

    def ingest(payload):
        response = client.post(
            f"/api/admin/sources/{source['id']}/offers",
            headers=auth(token),
            json={"external_id": "N-1", "market_code": "LV", "payload": payload},
        )
        assert response.status_code == 202, response.text
        return response.json()

    older = {"name": "Apple iPad mini (A17 Pro) 128GB", "price": "599"}
    ingest(older)
    newest = ingest({"name": "Apple iPad mini (A17 Pro) 128GB", "price": "579"})

    async def readings(raw_id) -> int:
        async with session_factory() as session:
            return await session.scalar(
                select(func.count())
                .select_from(NormalizedOffer)
                .where(NormalizedOffer.raw_offer_id == raw_id)
            )

    async def age(raw_id) -> None:
        """What a reading made before a rule moved looks like: another version."""
        from sqlalchemy import update

        async with session_factory() as session:
            await session.execute(
                update(NormalizedOffer)
                .where(NormalizedOffer.raw_offer_id == raw_id)
                .values(ruleset_version="an-older-ruleset")
            )
            await session.commit()

    event_loop.run_until_complete(age(newest["raw_offer_id"]))
    before = event_loop.run_until_complete(readings(newest["raw_offer_id"]))
    run = start(client, token, source["id"], kind="reparse")
    taken(event_loop, run["id"])
    handed = client.post(
        f"/api/worker/sources/{source['id']}/offers/batch",
        headers=auth(worker_token(client)),
        json={
            "market_code": "LV",
            "run_id": run["id"],
            "offers": [{"external_id": "N-1", "payload": older}],
        },
    )
    assert handed.status_code == 202, handed.text
    assert event_loop.run_until_complete(readings(newest["raw_offer_id"])) == before + 1


def test_a_reparse_waiting_means_the_one_before_it_leaves_settling_to_it(client, event_loop):
    """Settling walks the whole queue; twenty reparses settled twenty times took an hour."""
    from app.db.session import session_factory
    from app.features.runs.service import RunService

    async def waiting() -> bool:
        async with session_factory() as session:
            return await RunService(session).reparses_waiting()

    token = admin_token(client)
    source = channel(client, token, cron_full=None, cron_quick=None)
    assert event_loop.run_until_complete(waiting()) is False
    run = start(client, token, source["id"], kind="reparse")
    assert event_loop.run_until_complete(waiting()) is True
    client.post(f"/api/admin/runs/{run['id']}/cancel", headers=auth(token))
    assert event_loop.run_until_complete(waiting()) is False


def test_a_channel_with_no_snapshots_is_reread_from_its_payloads(client, event_loop):
    """Seven phone channels were collected before snapshots were kept, and a reparse of each
    read nothing; their stored payloads are enough."""
    from sqlalchemy import func, select, update

    from app.db.models import NormalizedOffer, RawOffer
    from app.db.session import session_factory

    token = admin_token(client)
    source = channel(client, token, cron_full=None, cron_quick=None)
    for n in range(3):
        response = client.post(
            f"/api/admin/sources/{source['id']}/offers",
            headers=auth(token),
            json={
                "external_id": f"R-{n}",
                "market_code": "LV",
                "payload": {"name": f"Apple iPhone 15 {n}", "price": "700"},
            },
        )
        assert response.status_code == 202, response.text

    async def age_and_count(age: bool) -> int:
        async with session_factory() as session:
            if age:
                await session.execute(update(NormalizedOffer).values(ruleset_version="old"))
                await session.commit()
            return await session.scalar(
                select(func.count())
                .select_from(NormalizedOffer)
                .join(RawOffer, RawOffer.id == NormalizedOffer.raw_offer_id)
                .where(RawOffer.source_id == source["id"], NormalizedOffer.ruleset_version != "old")
            )

    assert event_loop.run_until_complete(age_and_count(True)) == 0
    url = f"/api/admin/sources/{source['id']}/reread"
    first = client.post(url, headers=auth(token), params={"limit": 2}).json()
    assert (first["read"], first["next_after_id"] is not None) == (2, True)
    rest = client.post(
        url, headers=auth(token), params={"limit": 2, "after_id": first["next_after_id"]}
    ).json()
    assert (rest["read"], rest["next_after_id"]) == (1, None)
    assert event_loop.run_until_complete(age_and_count(False)) == 3
