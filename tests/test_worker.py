"""The collector's own audience, and what it may and may not reach.

The boundary is the token audience, as it already is between the two panels. A worker
token is refused by the admin panel before any role check runs, and an admin token is
refused here — which matters because a parser is the one thing in the system that runs
hostile input through itself all day.
"""

import pytest

from tests.test_auth import auth, tokens
from tests.test_matching import admin_token
from tests.test_runs import channel, start

WORKER = {"email": "worker@example.com", "password": "worker-password"}


def worker_token(client) -> str:
    response = client.post("/api/worker/auth/login", json=WORKER)
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def a_run(client, admin):
    source = channel(client, admin, cron_full=None, cron_quick=None)
    return source, start(client, admin, source["id"])


# --- the boundary ---


def test_a_worker_token_is_refused_by_the_admin_panel(client):
    token = worker_token(client)
    assert client.get("/api/admin/users", headers=auth(token)).status_code == 401
    assert client.get("/api/admin/runs", headers=auth(token)).status_code == 401


def test_an_admin_token_is_refused_by_the_collector_routes(client):
    """Not a convenience: an admin token here would make the narrow audience pointless."""
    token = admin_token(client)
    assert client.get("/api/worker/runs/1", headers=auth(token)).status_code == 401


def test_a_worker_cannot_sign_in_to_a_panel(client):
    """A machine account is not a person's, in either direction."""
    for path in ("/api/auth/login", "/api/admin/auth/login"):
        response = client.post(path, json=WORKER)
        assert response.status_code == 401, response.text
        assert response.json()["error"]["code"] == "wrong_panel"


def test_a_customer_cannot_sign_in_as_a_collector(client):
    response = client.post(
        "/api/worker/auth/login",
        json={"email": "customer@example.com", "password": "customer-password"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "wrong_panel"


def test_the_collector_reaches_exactly_five_routes(client):
    """A route added to the worker router is a decision, so it should be visible here."""
    from app.main import app

    reachable = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/worker")
        for method in operations
    }
    assert reachable == {
        ("POST", "/api/worker/auth/login"),
        ("POST", "/api/worker/auth/refresh"),
        ("GET", "/api/worker/runs/{run_id}"),
        ("POST", "/api/worker/runs/{run_id}/finish"),
        ("POST", "/api/worker/sources/{source_id}/offers/batch"),
    }


# --- the job ---


def test_the_job_carries_the_channel_declaration(client):
    """Asked for rather than passed on a command line, so a hand-started worker agrees."""
    admin = admin_token(client)
    source, run = a_run(client, admin)
    token = worker_token(client)

    job = client.get(f"/api/worker/runs/{run['id']}", headers=auth(token)).json()
    assert job["run_id"] == run["id"]
    assert job["source_slug"] == source["slug"]
    assert job["kind"] == "full"
    assert job["access"] == "retail"
    assert job["decode"] == "markup"
    # Already chosen by the kind, so the worker cannot pick the wrong list.
    assert job["delivers"] == ["catalogue", "price", "availability"]


def test_a_quick_job_says_only_what_the_cheap_pass_brings(client):
    admin = admin_token(client)
    source = channel(client, admin, cron_full=None, cron_quick=None)
    run = start(client, admin, source["id"], "quick")
    token = worker_token(client)

    job = client.get(f"/api/worker/runs/{run['id']}", headers=auth(token)).json()
    assert job["delivers"] == ["price"]


# --- handing over and reporting ---


def test_a_collector_hands_over_a_pass_and_reports(client):
    admin = admin_token(client)
    source, run = a_run(client, admin)
    token = worker_token(client)

    handed = client.post(
        f"/api/worker/sources/{source['id']}/offers/batch",
        headers=auth(token),
        json={
            "market_code": "LV",
            "run_id": run["id"],
            "offers": [{"external_id": "W-1", "payload": {"name": "Thing", "ean": "194253000001"}}],
        },
    )
    assert handed.status_code == 202, handed.text
    assert handed.json()["accepted"] == 1

    done = client.post(
        f"/api/worker/runs/{run['id']}/finish",
        headers=auth(token),
        json={"items_seen": 1, "items_ingested": 1, "coverage": {"price": 1.0}},
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "ok"


def test_a_handed_over_pass_leaves_no_audit_entry(client):
    """The trail records what an administrator did, and a crawl is not that.

    What a run collected is recorded on the run, which is where somebody would look.
    """
    admin = admin_token(client)
    source, run = a_run(client, admin)
    token = worker_token(client)

    client.post(
        f"/api/worker/sources/{source['id']}/offers/batch",
        headers=auth(token),
        json={
            "market_code": "LV",
            "run_id": run["id"],
            "offers": [{"external_id": "W-1", "payload": {"name": "Thing"}}],
        },
    )

    entries = client.get("/api/admin/audit", headers=auth(admin)).json()["items"]
    assert not [e for e in entries if e["path"].startswith("/api/worker")]


# --- the worker process, end to end, without a socket ---


@pytest.fixture
def collector(client):
    """A Collector wired straight to the app, so the real HTTP path runs in-process."""
    import httpx2

    from app.features.runs.client import Collector
    from app.main import app

    return Collector(
        base_url="http://testserver",
        client=httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app)),
    )


def test_the_worker_signs_itself_in_and_finishes_its_run(client, event_loop, collector):
    """Its own credentials, its own audience, its own reason for failing."""
    from app.features.runs.worker import main

    admin = admin_token(client)
    _, run = a_run(client, admin)

    code = event_loop.run_until_complete(main(run["id"], collector=collector))
    assert code == 1  # no channel is implemented, so every run fails

    runs = client.get("/api/admin/runs", headers=auth(admin)).json()["items"]
    finished = next(r for r in runs if r["id"] == run["id"])
    assert finished["status"] == "failed"
    assert "no channel implementation" in finished["error"]


def test_a_worker_that_cannot_reach_the_service_says_so(client, event_loop):
    """Nothing can be reported through a service that is not answering."""
    import httpx2

    from app.features.runs.client import Collector
    from app.features.runs.worker import main

    async def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused")

    broken = Collector(
        base_url="http://testserver",
        client=httpx2.AsyncClient(transport=httpx2.MockTransport(refuse)),
    )
    assert event_loop.run_until_complete(main(1, collector=broken)) == 1


def test_customer_and_admin_tokens_are_unaffected(client):
    """The third audience must not have loosened the two that existed."""
    customer = tokens(client, {"email": "customer@example.com", "password": "customer-password"})
    assert client.get("/api/auth/me", headers=auth(customer["access_token"])).status_code == 200
    assert client.get("/api/admin/users", headers=auth(customer["access_token"])).status_code == 401


# --- reading a shop's products side by side ---


def a_slow_shop(count: int, *, in_flight: list[int]):
    """A channel whose products take time to fetch, and which records how many were at once."""
    import asyncio

    from app.features.runs.channel import Listing, Part, Snapshot

    class Slow:
        slug = "slow-shop"

        def __init__(self) -> None:
            self.now = 0

        async def discover(self, fetcher, job):
            return [Listing(external_id=str(n), url=f"http://shop/{n}") for n in range(count)]

        async def fetch(self, fetcher, listing):
            self.now += 1
            in_flight.append(self.now)
            try:
                await asyncio.sleep(0.02)
            finally:
                self.now -= 1
            return Snapshot(
                external_id=listing.external_id,
                parts=[Part(role="detail", url=listing.url, status=200, body="{}")],
            )

        def parse(self, snapshot):
            return {"id": snapshot.external_id, "price": "1.00", "currency": "EUR"}

        def read_listing(self, listing):
            return {"id": listing.external_id}

    return Slow()


def test_products_are_read_side_by_side(client, event_loop, tmp_path):
    """The throttle is the fetcher's, not the loop's. Awaiting each product before starting
    the next pinned a whole run to one slot: 1400 cards took half an hour at a rate that
    could read them in eight."""
    from app.core.config import settings
    from app.features.runs.schemas import Job, Kind
    from app.features.runs.snapshots import SnapshotStore
    from app.features.runs.worker import _read_all

    in_flight: list[int] = []
    channel = a_slow_shop(24, in_flight=in_flight)
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
    listings = event_loop.run_until_complete(channel.discover(None, job))
    payloads, failed = event_loop.run_until_complete(
        _read_all(job, channel, None, SnapshotStore(tmp_path), listings)
    )

    assert (len(payloads), failed) == (24, 0)
    assert max(in_flight) > 1, "products were read one at a time"
    assert max(in_flight) <= settings.fetch_concurrency, "the pool is the fetcher's own size"
    # However the requests finish, the run reports in the order the shop listed.
    assert [p["external_id"] for p in payloads] == [str(n) for n in range(24)]


def test_one_product_failing_is_one_product_failing(client, event_loop, tmp_path):
    """A run that threw away the pass because the ninth card was broken would report the
    shop as closed."""
    from app.features.runs.schemas import Job, Kind
    from app.features.runs.snapshots import SnapshotStore
    from app.features.runs.worker import _read_all

    channel = a_slow_shop(10, in_flight=[])
    broken = channel.parse

    def parse(snapshot):
        if snapshot.external_id in {"3", "7"}:
            raise ValueError("this card is nonsense")
        return broken(snapshot)

    channel.parse = parse
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
    listings = event_loop.run_until_complete(channel.discover(None, job))
    payloads, failed = event_loop.run_until_complete(
        _read_all(job, channel, None, SnapshotStore(tmp_path), listings)
    )

    assert (len(payloads), failed) == (8, 2)
    assert {"3", "7"}.isdisjoint(p["external_id"] for p in payloads)
    # The bytes that broke it are kept apart, which is what makes the fix five minutes.
    assert set(SnapshotStore(tmp_path).stored("slow-shop", failed=True)) == {"3", "7"}


def test_a_store_that_cannot_be_written_to_fails_the_run_once(client, event_loop, tmp_path):
    """Not a fact about a product — a fact about the machine. Found one product at a time it
    reads as a shop that served 1400 broken cards, which is the wrong thing to go and look
    at."""
    from app.features.runs.schemas import Job, Kind
    from app.features.runs.snapshots import SnapshotStore
    from app.features.runs.worker import collect

    shut = tmp_path / "shut"
    shut.mkdir(mode=0o500)
    job = Job(
        run_id=1,
        source_id=1,
        # A channel that is registered, so the run gets past that check and stops on this
        # one. It never reaches the network: the store is refused before the first request.
        source_slug="rdveikals-phones",
        shop_slug="rdveikals",
        kind=Kind.FULL,
        access="retail",
        decode="markup",
        base_url=None,
        market_codes=["LV"],
        delivers=["catalogue"],
    )
    result = event_loop.run_until_complete(collect(job, collector=None, store=SnapshotStore(shut)))
    assert result.items_seen == 0
    assert "cannot write snapshots" in result.error


def test_a_reparse_reports_the_id_the_shop_gave_and_not_the_file_name(client, event_loop, tmp_path):
    """A file name has to be safe to put in a path, so a slash in an identifier becomes an
    underscore. Reported under that name, a reparse does not re-read the product — it
    invents a second one beside it, and the shop doubles."""
    from app.features.runs.channel import Part, Snapshot
    from app.features.runs.schemas import Job, Kind
    from app.features.runs.snapshots import SnapshotStore
    from app.features.runs.worker import _reparse

    store = SnapshotStore(tmp_path)
    store.save(
        "slow-shop",
        Snapshot(
            external_id="MJXP4HX/A",
            parts=[Part(role="detail", url="http://shop/1", status=200, body="{}")],
        ),
    )

    class Channel:
        slug = "slow-shop"

        def parse(self, snapshot):
            return {"id": snapshot.external_id}

    job = Job(
        run_id=1,
        source_id=1,
        source_slug="slow-shop",
        kind=Kind.REPARSE,
        access="retail",
        decode="markup",
        base_url=None,
        market_codes=["LV"],
        delivers=["catalogue"],
    )
    seen, payloads, failed = _reparse(job, Channel(), store)

    assert (seen, failed) == (1, 0)
    assert [p["external_id"] for p in payloads] == ["MJXP4HX/A"]
