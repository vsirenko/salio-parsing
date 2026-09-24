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
