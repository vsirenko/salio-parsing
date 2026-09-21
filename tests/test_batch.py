"""Many observations in one request, gzipped.

One at a time, a pass of a nine-hundred-product shop is nine hundred requests, nine
hundred transactions and nine hundred audit entries. The last is the real objection: the
trail exists to show what an administrator did.
"""

import gzip
import json

from app.core.config import settings
from tests.test_auth import auth
from tests.test_matching import admin_token
from tests.test_offers import setup_source


def batch(client, token, source_id, offers, *, market="LV", run_id=None, expect=202, gzipped=False):
    body = {"market_code": market, "offers": offers}
    if run_id is not None:
        body["run_id"] = run_id

    url = f"/api/admin/sources/{source_id}/offers/batch"
    if gzipped:
        response = client.post(
            url,
            headers={
                **auth(token),
                "content-type": "application/json",
                "content-encoding": "gzip",
            },
            content=gzip.compress(json.dumps(body).encode()),
        )
    else:
        response = client.post(url, headers=auth(token), json=body)

    assert response.status_code == expect, response.text
    return response.json()


def listing(external_id, **over):
    return {
        "external_id": external_id,
        "payload": {"name": f"Phone {external_id}", "price": "199.00", **over},
    }


# --- the batch ---


def test_a_batch_goes_in_as_one(client):
    token = admin_token(client)
    _, source = setup_source(client, token)

    result = batch(client, token, source["id"], [listing("SKU-1"), listing("SKU-2")])
    assert result == {
        "accepted": 2,
        "failed": 0,
        "stored": 2,
        "offers_created": 2,
        "failures": [],
    }

    offers = client.get("/api/admin/offers", headers=auth(token)).json()
    assert {o["external_id"] for o in offers["items"]} == {"SKU-1", "SKU-2"}


def test_an_unchanged_listing_writes_nothing(client):
    """The same rule as a single ingest: one row per distinct content, not per fetch."""
    token = admin_token(client)
    _, source = setup_source(client, token)
    batch(client, token, source["id"], [listing("SKU-1")])

    again = batch(client, token, source["id"], [listing("SKU-1")])
    assert (again["accepted"], again["stored"], again["offers_created"]) == (1, 0, 0)


def test_one_bad_card_does_not_throw_away_the_pass(client):
    """The case `runs.items_failed` exists to record."""
    token = admin_token(client)
    shop, source = setup_source(client, token, marketplace=True)

    # A marketplace offer that does not say which trader it belongs to.
    result = batch(
        client,
        token,
        source["id"],
        [
            listing(
                "SKU-1",
            ),
            {**listing("SKU-2"), "seller_external_id": None},
            listing("SKU-3"),
        ],
    )
    assert result["accepted"] == 0
    assert result["failed"] == 3

    # With sellers named, the same batch goes in.
    good = batch(
        client,
        token,
        source["id"],
        [
            {**listing("SKU-1"), "seller_external_id": "trader-a"},
            {**listing("SKU-2"), "seller_external_id": None},
            {**listing("SKU-3"), "seller_external_id": "trader-b"},
        ],
    )
    assert good["accepted"] == 2
    assert good["failed"] == 1
    # Named, because a batch that reports "one failed" is a batch nobody can fix.
    assert good["failures"] == [
        {
            "external_id": "SKU-2",
            "code": "seller_required",
            "message": good["failures"][0]["message"],
        }
    ]
    assert "marketplace" in good["failures"][0]["message"]


def test_a_failed_item_leaves_nothing_behind(client):
    """The savepoint. A plain flush would abort the transaction on the first bad row."""
    token = admin_token(client)
    shop, source = setup_source(client, token, marketplace=True)

    batch(
        client,
        token,
        source["id"],
        [
            {**listing("SKU-1"), "seller_external_id": None},
            {**listing("SKU-2"), "seller_external_id": "t"},
        ],
    )
    offers = client.get("/api/admin/offers", headers=auth(token)).json()
    assert [o["external_id"] for o in offers["items"]] == ["SKU-2"]


def test_a_batch_larger_than_allowed_is_refused(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    kept = settings.max_batch_offers
    settings.max_batch_offers = 2
    try:
        body = batch(
            client,
            token,
            source["id"],
            [listing(f"SKU-{n}") for n in range(3)],
            expect=422,
        )
        assert body["error"]["code"] == "batch_too_large"
    finally:
        settings.max_batch_offers = kept


def test_an_empty_batch_is_refused(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    response = client.post(
        f"/api/admin/sources/{source['id']}/offers/batch",
        headers=auth(token),
        json={"market_code": "LV", "offers": []},
    )
    assert response.status_code == 422


# --- the run it belongs to ---


def test_a_batch_remembers_which_run_brought_it(client):
    from tests.test_runs import channel, start

    token = admin_token(client)
    source = channel(client, token, cron_full=None, cron_quick=None)
    run = start(client, token, source["id"])

    batch(client, token, source["id"], [listing("SKU-1")], run_id=run["id"])

    offers = client.get("/api/admin/offers", headers=auth(token)).json()["items"]
    raw = client.get(f"/api/admin/offers/{offers[0]['id']}/raw", headers=auth(token)).json()
    assert raw[0]["run_id"] == run["id"]


def test_a_batch_naming_a_run_that_does_not_exist(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    batch(client, token, source["id"], [listing("SKU-1")], run_id=9999, expect=404)


# --- one entry in the trail, not nine hundred ---


def test_a_batch_is_one_audit_entry(client):
    """Counted by path rather than by total: reading the trail is itself an admin request."""
    token = admin_token(client)
    _, source = setup_source(client, token)

    batch(client, token, source["id"], [listing(f"SKU-{n}") for n in range(5)])

    entries = client.get("/api/admin/audit", headers=auth(token)).json()["items"]
    ingests = [e for e in entries if e["path"].endswith("/offers/batch")]
    assert len(ingests) == 1

    changes = ingests[0]["changes"]
    assert changes["ingested_batch"] == 5
    assert changes["accepted"] == 5
    assert changes["failed"] == 0


# --- gzip ---


def test_a_gzipped_batch_is_read(client):
    token = admin_token(client)
    _, source = setup_source(client, token)

    result = batch(
        client, token, source["id"], [listing(f"SKU-{n}") for n in range(20)], gzipped=True
    )
    assert result["accepted"] == 20


def test_a_body_that_expands_too_far_is_refused(client):
    """A few kilobytes of gzip expand to tens of megabytes; the cap is checked as it goes.

    Aimed at the real configured limit rather than at a patched one: the middleware takes
    its cap when the app is built, so lowering the setting afterwards changes nothing and
    a test that did it would be measuring the default while claiming otherwise.
    """
    token = admin_token(client)
    _, source = setup_source(client, token)

    oversized = (settings.max_decompressed_body_mb + 4) * 1024 * 1024
    bomb = gzip.compress(b'{"market_code":"LV","offers":[' + b" " * oversized + b"]}")
    assert len(bomb) < 200_000, "the point is that a small upload expands to a large body"

    response = client.post(
        f"/api/admin/sources/{source['id']}/offers/batch",
        headers={
            **auth(token),
            "content-type": "application/json",
            "content-encoding": "gzip",
        },
        content=bomb,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_request"


def test_batch_ingestion_requires_an_admin_token(client):
    assert client.post("/api/admin/sources/1/offers/batch", json={}).status_code == 401
