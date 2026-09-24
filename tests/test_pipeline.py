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
