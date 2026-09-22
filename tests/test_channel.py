"""The channel runtime: fetching, snapshots, and a run that actually collects something.

A stub channel stands in for a shop, served by a transport inside the process. Everything
else is real — the fetcher's retries, the snapshot store on disk, the worker's HTTP path
through the collector audience, and the coverage the service measures on what arrives.
"""

import json

import httpx2
import pytest

from app.features.runs.channel import CHANNELS, Listing, Part, Snapshot, register
from tests.test_auth import auth
from tests.test_matching import admin_token
from tests.test_runs import channel as make_channel
from tests.test_runs import start
from tests.test_worker import a_run

CARDS = {
    "P-1": {"name": "Apple iPhone 15 Pro", "ean": "194253000001", "price": "1199.00"},
    "P-2": {"name": "Samsung Galaxy S24", "ean": "880609400001", "price": "899.00"},
    "P-3": {"name": "A thing with no barcode", "price": "19.99"},
}


class Shop:
    """A stub channel. Its slug has to match the source it serves."""

    def __init__(self, slug: str, *, breaks: set[str] | None = None) -> None:
        self.slug = slug
        self.breaks = breaks or set()

    async def discover(self, fetcher, job):
        part = await fetcher.get("https://shop.test/listing", role="listing")
        return [
            Listing(external_id=external_id, url=f"https://shop.test/p/{external_id}", card=card)
            for external_id, card in json.loads(part.body).items()
        ]

    async def fetch(self, fetcher, listing):
        part = await fetcher.get(listing.url)
        return Snapshot(external_id=listing.external_id, parts=[part])

    def parse(self, snapshot):
        if snapshot.external_id in self.breaks:
            raise ValueError("the page changed shape")
        return json.loads(snapshot.part("detail").body)

    def read_listing(self, listing):
        return {"name": listing.card["name"], "price": listing.card["price"]}


@pytest.fixture
def shop(tmp_path):
    """A registered stub channel, its transport, and a snapshot store under tmp."""
    from app.features.runs.fetching import Fetcher
    from app.features.runs.snapshots import SnapshotStore

    served = {"requests": 0, "fail_once": set()}

    async def serve(request: httpx2.Request) -> httpx2.Response:
        served["requests"] += 1
        path = request.url.path
        if path == "/listing":
            return httpx2.Response(200, json=CARDS)
        external_id = path.rsplit("/", 1)[-1]
        if external_id in served["fail_once"]:
            served["fail_once"].discard(external_id)
            return httpx2.Response(503)
        return httpx2.Response(200, json=CARDS[external_id])

    made = Shop("rd-site")
    register(made)
    try:
        yield (
            made,
            served,
            lambda: Fetcher(
                rate=0, client=httpx2.AsyncClient(transport=httpx2.MockTransport(serve))
            ),
            SnapshotStore(tmp_path),
        )
    finally:
        CHANNELS.pop(made.slug, None)


@pytest.fixture
def collector(client):
    from app.features.runs.client import Collector
    from app.main import app

    return Collector(
        base_url="http://testserver",
        client=httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app)),
    )


# --- a full pass, end to end ---


def test_a_full_pass_collects_stores_and_reports(client, event_loop, shop, collector):
    from app.features.runs.worker import collect

    made, served, fetcher, store = shop
    admin = admin_token(client)
    source, run = a_run(client, admin)

    job = event_loop.run_until_complete(collector.job(run["id"]))
    result = event_loop.run_until_complete(collect(job, collector, fetcher=fetcher(), store=store))

    assert (result.items_seen, result.items_ingested, result.items_failed) == (3, 3, 0)
    # Measured by the service on its own reading, not by the parser on itself.
    assert result.coverage["title"] == 1.0
    assert result.coverage["gtin"] == pytest.approx(2 / 3, abs=0.001)

    offers = client.get("/api/admin/offers", headers=auth(admin)).json()
    assert {o["external_id"] for o in offers["items"]} == set(CARDS)

    # The bytes that produced each observation are on disk.
    assert store.stored(made.slug) == ["P-1", "P-2", "P-3"]
    assert store.stored(made.slug, failed=True) == []


def test_the_offers_carry_the_run_that_brought_them(client, event_loop, shop, collector):
    from app.features.runs.worker import collect

    _, _, fetcher, store = shop
    admin = admin_token(client)
    _, run = a_run(client, admin)

    job = event_loop.run_until_complete(collector.job(run["id"]))
    event_loop.run_until_complete(collect(job, collector, fetcher=fetcher(), store=store))

    offers = client.get("/api/admin/offers", headers=auth(admin)).json()["items"]
    raw = client.get(f"/api/admin/offers/{offers[0]['id']}/raw", headers=auth(admin)).json()
    assert raw[0]["run_id"] == run["id"]


# --- one product failing is one product failing ---


def test_a_broken_parse_costs_one_product_and_keeps_the_bytes(client, event_loop, shop, collector):
    """The run that threw away the pass because one card was odd would report a closed shop."""
    from app.features.runs.worker import collect

    made, _, fetcher, store = shop
    made.breaks = {"P-2"}
    admin = admin_token(client)
    _, run = a_run(client, admin)

    job = event_loop.run_until_complete(collector.job(run["id"]))
    result = event_loop.run_until_complete(collect(job, collector, fetcher=fetcher(), store=store))

    assert (result.items_seen, result.items_ingested, result.items_failed) == (3, 2, 1)
    # Kept apart, so the parser is fixed against the bytes that broke it.
    assert store.stored(made.slug, failed=True) == ["P-2"]
    assert "P-2" not in store.stored(made.slug)


def test_a_fixed_parser_clears_the_broken_example(client, event_loop, shop, collector):
    from app.features.runs.worker import collect

    made, _, fetcher, store = shop
    admin = admin_token(client)
    source = make_channel(client, admin, cron_full=None, cron_quick=None)

    made.breaks = {"P-2"}
    first = start(client, admin, source["id"])
    job = event_loop.run_until_complete(collector.job(first["id"]))
    event_loop.run_until_complete(collect(job, collector, fetcher=fetcher(), store=store))
    assert store.stored(made.slug, failed=True) == ["P-2"]

    made.breaks = set()
    client.post(
        f"/api/admin/runs/{first['id']}/finish",
        headers=auth(admin),
        json={"items_seen": 3, "items_ingested": 2},
    )
    second = start(client, admin, source["id"])
    job = event_loop.run_until_complete(collector.job(second["id"]))
    event_loop.run_until_complete(collect(job, collector, fetcher=fetcher(), store=store))

    assert store.stored(made.slug, failed=True) == []


# --- a cheap pass opens no cards ---


def test_a_quick_pass_reads_the_listing_and_nothing_else(client, event_loop, shop, collector):
    from app.features.runs.worker import collect

    _, served, fetcher, store = shop
    admin = admin_token(client)
    source = make_channel(client, admin, cron_full=None, cron_quick=None)
    run = start(client, admin, source["id"], "quick")

    job = event_loop.run_until_complete(collector.job(run["id"]))
    result = event_loop.run_until_complete(collect(job, collector, fetcher=fetcher(), store=store))

    assert result.items_ingested == 3
    # One request for the listing. Nothing opened a card, so nothing was snapshotted.
    assert served["requests"] == 1
    assert store.stored("rd-site") == []


# --- the fetcher ---


def test_a_shop_that_wobbles_is_retried(client, event_loop, shop, collector):
    from app.features.runs.worker import collect

    _, served, fetcher, store = shop
    served["fail_once"] = {"P-1", "P-3"}
    admin = admin_token(client)
    _, run = a_run(client, admin)

    job = event_loop.run_until_complete(collector.job(run["id"]))
    result = event_loop.run_until_complete(collect(job, collector, fetcher=fetcher(), store=store))
    assert result.items_ingested == 3


def test_a_shop_that_stays_down_costs_those_products(client, event_loop, shop, collector):
    from app.features.runs.fetching import Fetcher
    from app.features.runs.worker import collect

    made, _, _, store = shop
    admin = admin_token(client)
    _, run = a_run(client, admin)

    async def refuse(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/listing":
            return httpx2.Response(200, json=CARDS)
        return httpx2.Response(503)

    job = event_loop.run_until_complete(collector.job(run["id"]))
    result = event_loop.run_until_complete(
        collect(
            job,
            collector,
            fetcher=Fetcher(
                rate=0,
                retries=1,
                client=httpx2.AsyncClient(transport=httpx2.MockTransport(refuse)),
            ),
            store=store,
        )
    )
    assert (result.items_seen, result.items_ingested, result.items_failed) == (3, 0, 3)


def test_discovery_failing_fails_the_run(client, event_loop, shop, collector):
    """Unlike one product, this leaves nothing to collect — so the run carries the reason."""
    from app.features.runs.fetching import Fetcher
    from app.features.runs.worker import collect

    _, _, _, store = shop
    admin = admin_token(client)
    _, run = a_run(client, admin)

    async def refuse(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(500)

    job = event_loop.run_until_complete(collector.job(run["id"]))
    result = event_loop.run_until_complete(
        collect(
            job,
            collector,
            fetcher=Fetcher(
                rate=0,
                retries=0,
                client=httpx2.AsyncClient(transport=httpx2.MockTransport(refuse)),
            ),
            store=store,
        )
    )
    assert result.items_ingested == 0
    assert "discover" in result.error


# --- the snapshot store ---


# --- reading the bytes again ---


def test_a_reparse_reads_the_store_and_never_the_network(client, event_loop, shop, collector):
    """A parser is judged against the bytes that were served, not the site as it is now."""
    from app.features.runs.worker import collect

    made, served, fetcher, store = shop
    admin = admin_token(client)
    source = make_channel(client, admin, cron_full=None, cron_quick=None)

    crawl = start(client, admin, source["id"])
    job = event_loop.run_until_complete(collector.job(crawl["id"]))
    event_loop.run_until_complete(collect(job, collector, fetcher=fetcher(), store=store))
    client.post(
        f"/api/admin/runs/{crawl['id']}/finish",
        headers=auth(admin),
        json={"items_seen": 3, "items_ingested": 3},
    )
    crawled = served["requests"]

    again = start(client, admin, source["id"], "reparse")
    job = event_loop.run_until_complete(collector.job(again["id"]))
    result = event_loop.run_until_complete(collect(job, collector, store=store))

    assert (result.items_seen, result.items_ingested, result.items_failed) == (3, 3, 0)
    # Not one request. That is the point.
    assert served["requests"] == crawled


def test_a_fix_is_judged_by_reparsing(client, event_loop, shop, collector):
    """The reason the failed area exists: the broken example is what the fix was for."""
    from app.features.runs.worker import collect

    made, _, fetcher, store = shop
    made.breaks = {"P-2"}
    admin = admin_token(client)
    source = make_channel(client, admin, cron_full=None, cron_quick=None)

    crawl = start(client, admin, source["id"])
    job = event_loop.run_until_complete(collector.job(crawl["id"]))
    event_loop.run_until_complete(collect(job, collector, fetcher=fetcher(), store=store))
    client.post(
        f"/api/admin/runs/{crawl['id']}/finish",
        headers=auth(admin),
        json={"items_seen": 3, "items_ingested": 2},
    )
    assert store.stored(made.slug, failed=True) == ["P-2"]

    # The parser is fixed, and the question is whether it helped.
    made.breaks = set()
    again = start(client, admin, source["id"], "reparse")
    job = event_loop.run_until_complete(collector.job(again["id"]))
    result = event_loop.run_until_complete(collect(job, collector, store=store))

    assert (result.items_seen, result.items_ingested, result.items_failed) == (3, 3, 0)
    assert store.stored(made.slug, failed=True) == []
    assert store.stored(made.slug) == ["P-1", "P-2", "P-3"]


def test_a_fix_that_made_things_worse_says_so(client, event_loop, shop, collector):
    from app.features.runs.worker import collect

    made, _, fetcher, store = shop
    admin = admin_token(client)
    source = make_channel(client, admin, cron_full=None, cron_quick=None)

    crawl = start(client, admin, source["id"])
    job = event_loop.run_until_complete(collector.job(crawl["id"]))
    event_loop.run_until_complete(collect(job, collector, fetcher=fetcher(), store=store))
    client.post(
        f"/api/admin/runs/{crawl['id']}/finish",
        headers=auth(admin),
        json={"items_seen": 3, "items_ingested": 3},
    )

    # A "fix" that breaks one that used to work.
    made.breaks = {"P-1"}
    again = start(client, admin, source["id"], "reparse")
    job = event_loop.run_until_complete(collector.job(again["id"]))
    result = event_loop.run_until_complete(collect(job, collector, store=store))

    assert result.items_failed == 1
    # Its bytes move in with the other broken examples, ready for the next attempt.
    assert store.stored(made.slug, failed=True) == ["P-1"]


def test_a_reparse_restates_what_the_crawl_knew(client, event_loop, shop, collector, tmp_path):
    """A snapshot carrying only bytes could not say which trader a listing belonged to."""
    from app.features.runs.snapshots import SnapshotStore

    _, _, fetcher, store = shop
    admin = admin_token(client)
    source = make_channel(client, admin, cron_full=None, cron_quick=None)
    run = start(client, admin, source["id"])

    from app.features.runs.worker import collect

    job = event_loop.run_until_complete(collector.job(run["id"]))
    event_loop.run_until_complete(collect(job, collector, fetcher=fetcher(), store=store))

    reloaded = SnapshotStore(store.root).load("rd-site", "P-1")
    assert reloaded.url == "https://shop.test/p/P-1"


def test_a_reparse_is_never_due(client):
    """It has no cron and is started by hand — which is also when it is wanted."""
    admin = admin_token(client)
    make_channel(client, admin, cron_full="* * * * *", cron_quick=None)

    due = client.get("/api/admin/runs/due", headers=auth(admin)).json()
    assert {item["kind"] for item in due} == {"full"}


def test_a_snapshot_round_trips(tmp_path):
    from app.features.runs.snapshots import SnapshotStore

    store = SnapshotStore(tmp_path)
    snapshot = Snapshot(
        external_id="P-1",
        parts=[Part(role="detail", url="https://shop.test/p/P-1", status=200, body='{"a":1}')],
    )
    store.save("rd-site", snapshot)

    back = store.load("rd-site", "P-1")
    assert back is not None
    assert back.external_id == "P-1"
    assert back.part("detail").body == '{"a":1}'
    assert back.part("stock") is None


def test_an_identifier_cannot_escape_its_directory(tmp_path):
    """Shop identifiers arrive from outside and end up in a path."""
    from app.features.runs.snapshots import SnapshotStore

    store = SnapshotStore(tmp_path)
    store.save("rd-site", Snapshot(external_id="../../etc/passwd", parts=[]))

    written = list(tmp_path.rglob("*.json.gz"))
    assert len(written) == 1
    assert written[0].parent == tmp_path / "rd-site"
    assert ".." not in written[0].name


def test_registering_the_same_channel_twice_is_refused(shop):
    with pytest.raises(ValueError, match="already registered"):
        register(Shop("rd-site"))


# --- how fast a shop is asked ---


def test_the_rate_is_a_ceiling_on_starts_not_a_tax_on_slots(event_loop):
    """The two limits are separate on purpose. Sleeping inside the concurrency gate made
    the real rate `concurrency / (delay + latency)`, so raising one and lengthening the
    other cancelled out and neither number said what it meant."""
    import asyncio
    import time

    from app.features.runs.fetching import Rate

    limiter = Rate(20)  # twenty a second, so ten starts span about half a second

    async def ten() -> float:
        began = time.perf_counter()
        await asyncio.gather(*(limiter.wait() for _ in range(10)))
        return time.perf_counter() - began

    took = event_loop.run_until_complete(ten())
    # Spaced rather than bursty: ten starts cannot all happen at once.
    assert took > 0.3, "the ceiling did not hold"
    # And jittered rather than exact, so a run is not a metronome.
    assert took < 0.9, "the ceiling is spacing more than it was asked to"


def test_no_rate_means_concurrency_is_the_only_limit(event_loop):
    import asyncio
    import time

    from app.features.runs.fetching import Rate

    limiter = Rate(0)

    async def many() -> float:
        began = time.perf_counter()
        await asyncio.gather(*(limiter.wait() for _ in range(100)))
        return time.perf_counter() - began

    assert event_loop.run_until_complete(many()) < 0.05
