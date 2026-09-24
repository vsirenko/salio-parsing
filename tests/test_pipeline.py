"""The pipeline counted, node by node, for a canvas to draw."""

from tests.test_auth import auth
from tests.test_offers import FEED_ROW, admin_token, ingest, setup_source


def stages(body: dict) -> dict[str, dict]:
    return {stage["key"]: stage for stage in body["stages"]}


def test_every_listing_is_counted_at_each_node_it_reached(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    for sku in ("SKU-1", "SKU-2"):
        ingest(
            client,
            token,
            source["id"],
            {"external_id": sku, "market_code": "LV", "payload": FEED_ROW},
        )

    body = client.get("/api/admin/pipeline", headers=auth(token)).json()
    nodes = stages(body)
    assert nodes["channels"]["count"] == 1
    assert nodes["listed"]["count"] == 2
    assert nodes["read"]["count"] == 2
    assert nodes["read"]["parts"]["with_gtin"] == 2
    # Nothing has been matched: nothing placed, and no edge claims otherwise.
    assert nodes["placed"]["count"] == 0
    assert {(e["source"], e["target"]): e["count"] for e in body["edges"]}[("listed", "read")] == 2
    (flow,) = body["sources"]
    assert (flow["source"], flow["listed"], flow["read"]) == ("rd-feed", 2, 2)


def test_it_narrows_to_one_channel_and_refuses_one_that_is_not_there(client):
    token = admin_token(client)
    setup_source(client, token)
    one = client.get("/api/admin/pipeline", params={"source": "rd-feed"}, headers=auth(token))
    assert one.status_code == 200 and one.json()["source"] == "rd-feed"
    missing = client.get("/api/admin/pipeline", params={"source": "nowhere"}, headers=auth(token))
    assert missing.status_code == 404
    assert (
        client.get(
            "/api/admin/pipeline", params={"category": "nothing"}, headers=auth(token)
        ).status_code
        == 404
    )


def test_one_run_is_drawn_from_what_its_worker_said_and_what_its_listings_became(
    client, event_loop
):
    from tests.test_runs import channel, start
    from tests.test_worker import taken, worker_token

    admin = admin_token(client)
    source = channel(client, admin, cron_full=None, cron_quick=None)
    run = start(client, admin, source["id"])
    queued = stages(client.get(f"/api/admin/pipeline/runs/{run['id']}", headers=auth(admin)).json())
    assert queued["discovered"]["count"] == 0
    taken(event_loop, run["id"])
    worker = worker_token(client)
    client.post(
        f"/api/worker/runs/{run['id']}/progress",
        headers=auth(worker),
        json={"phase": "reading", "discovered": 3, "read": 2, "failed": 1, "handed_over": 2},
    )
    handed = client.post(
        f"/api/worker/sources/{source['id']}/offers/batch",
        headers=auth(worker),
        json={
            "market_code": "LV",
            "run_id": run["id"],
            "offers": [
                {"external_id": sku, "payload": {**FEED_ROW, "ean": ean}}
                for sku, ean in (("R-1", "0194253000001"), ("R-2", "0194253000002"))
            ],
        },
    )
    assert handed.status_code == 202, handed.text

    live = client.get(f"/api/admin/pipeline/runs/{run['id']}", headers=auth(admin))
    assert live.status_code == 200, live.text
    body = live.json()
    nodes = stages(body)
    assert (body["status"], body["phase"]) == ("running", "reading")
    assert nodes["discovered"]["count"] == 3
    assert nodes["fetched"]["count"] == 2 and nodes["fetched"]["parts"]["failed"] == 1
    assert nodes["handed_over"]["count"] == 2
    assert nodes["read"]["count"] == 2
    assert nodes["read"]["parts"]["new_listings"] == 2
    assert nodes["placed"]["count"] == 0

    client.post(
        f"/api/worker/runs/{run['id']}/finish",
        headers=auth(worker),
        json={"items_seen": 3, "items_ingested": 2, "items_failed": 1},
    )
    done = stages(client.get(f"/api/admin/pipeline/runs/{run['id']}", headers=auth(admin)).json())
    # Finished, the run's own counts are the word, not the last report.
    assert done["discovered"]["count"] == 3 and done["fetched"]["count"] == 2

    assert client.get("/api/admin/pipeline/runs/999999", headers=auth(admin)).status_code == 404
