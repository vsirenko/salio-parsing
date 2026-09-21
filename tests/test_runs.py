"""One execution of one channel: what it earns the right to conclude, and when it starts.

The scheduler process is not here. Everything it decides is an ordinary query, so what it
would do is asserted through `GET /api/admin/runs/due` without starting anything.
"""

from tests.test_auth import auth
from tests.test_matching import admin_token
from tests.test_offers import post, setup_source

FULL = ["catalogue", "price", "availability"]


def channel(client, token, **over):
    """A retail channel with a cheap pass, running nightly and four times a day."""
    shop, _ = setup_source(client, token)
    body = {
        "slug": over.pop("slug", "rd-site"),
        "access": "retail",
        "decode": "markup",
        "delivers_full": FULL,
        "delivers_quick": ["price"],
        "is_enabled": True,
        "cron_full": "0 3 * * *",
        "cron_quick": "0 9,13,17,21 * * *",
        **over,
    }
    return post(client, token, f"/api/admin/shops/{shop['id']}/sources", body)


def start(client, token, source_id, kind="full", expect=201):
    response = client.post(
        f"/api/admin/sources/{source_id}/runs", headers=auth(token), params={"kind": kind}
    )
    assert response.status_code == expect, response.text
    return response.json()


def finish(client, token, run_id, **result):
    body = {"items_seen": 0, "items_ingested": 0, **result}
    response = client.post(f"/api/admin/runs/{run_id}/finish", headers=auth(token), json=body)
    assert response.status_code == 200, response.text
    return response.json()


# --- one live run, held by the database ---


def test_a_second_run_of_the_same_kind_is_refused(client):
    token = admin_token(client)
    source = channel(client, token)
    start(client, token, source["id"])

    response = client.post(
        f"/api/admin/sources/{source['id']}/runs", headers=auth(token), params={"kind": "full"}
    )
    assert response.status_code == 409
    # But the other kind is a different lane.
    start(client, token, source["id"], "quick")


def test_a_channel_with_no_quick_pass_cannot_run_one(client):
    token = admin_token(client)
    source = channel(client, token, delivers_quick=[], cron_quick=None)
    response = client.post(
        f"/api/admin/sources/{source['id']}/runs", headers=auth(token), params={"kind": "quick"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_quick_pass"


# --- the contract ---


def test_a_healthy_run_earns_the_right_to_believe_absences(client):
    token = admin_token(client)
    source = channel(client, token, min_items=50)
    run = start(client, token, source["id"])

    done = finish(
        client, token, run["id"], items_seen=900, items_ingested=898, coverage={"price": 0.99}
    )
    assert done["status"] == "ok"
    assert done["contract"]["verdict"] == "ok"


def test_a_collapsed_run_is_rejected_not_believed(client):
    """Three products instead of nine hundred: the three are real, the absences are not."""
    token = admin_token(client)
    source = channel(client, token, min_items=50)
    first = start(client, token, source["id"])
    finish(client, token, first["id"], items_seen=900, items_ingested=900, coverage={"price": 1.0})

    second = start(client, token, source["id"])
    done = finish(
        client, token, second["id"], items_seen=3, items_ingested=3, coverage={"price": 1.0}
    )

    assert done["status"] == "rejected"
    failed = {c["name"] for c in done["contract"]["checks"] if not c["passed"]}
    assert failed == {"min_items", "max_drop_pct"}


def test_a_drop_is_measured_from_the_last_accepted_run(client):
    """Against the previous run, two broken crawls in a row pass the second one."""
    token = admin_token(client)
    source = channel(client, token)
    first = start(client, token, source["id"])
    finish(
        client, token, first["id"], items_seen=1000, items_ingested=1000, coverage={"price": 1.0}
    )

    second = start(client, token, source["id"])
    assert (
        finish(
            client, token, second["id"], items_seen=500, items_ingested=500, coverage={"price": 1.0}
        )["status"]
        == "rejected"
    )

    # 450 is a 10% fall from the rejected 500 and a 55% fall from the accepted 1000.
    third = start(client, token, source["id"])
    done = finish(
        client, token, third["id"], items_seen=450, items_ingested=450, coverage={"price": 1.0}
    )
    assert done["status"] == "rejected"
    drop = next(c for c in done["contract"]["checks"] if c["name"] == "max_drop_pct")
    assert drop["got"] == 55.0


def test_the_first_run_has_nothing_to_fall_from(client):
    token = admin_token(client)
    source = channel(client, token)
    run = start(client, token, source["id"])
    done = finish(
        client, token, run["id"], items_seen=12, items_ingested=12, coverage={"price": 1.0}
    )

    assert done["status"] == "ok"
    drop = next(c for c in done["contract"]["checks"] if c["name"] == "max_drop_pct")
    assert drop["note"] == "no accepted run to compare against"


def test_price_coverage_is_only_asked_of_a_pass_that_carries_a_price(client):
    """Otherwise a pass that never sees a price would be rejected forever."""
    token = admin_token(client)
    source = channel(client, token, delivers_quick=["availability"], cron_quick="0 * * * *")
    run = start(client, token, source["id"], "quick")
    done = finish(client, token, run["id"], items_seen=900, items_ingested=900, coverage={})

    assert done["status"] == "ok"
    assert "min_price_coverage" not in {c["name"] for c in done["contract"]["checks"]}


def test_a_worker_that_broke_is_not_judged_on_its_numbers(client):
    token = admin_token(client)
    source = channel(client, token, min_items=50)
    run = start(client, token, source["id"])
    done = finish(client, token, run["id"], items_seen=0, items_ingested=0, error="TimeoutError")

    assert done["status"] == "failed"
    assert done["contract"]["verdict"] == "not_evaluated"
    assert done["error"] == "TimeoutError"


def test_a_finished_run_cannot_be_finished_twice(client):
    token = admin_token(client)
    source = channel(client, token)
    run = start(client, token, source["id"])
    finish(client, token, run["id"], items_seen=1, items_ingested=1, coverage={"price": 1.0})

    response = client.post(
        f"/api/admin/runs/{run['id']}/finish",
        headers=auth(token),
        json={"items_seen": 1, "items_ingested": 1},
    )
    assert response.status_code == 409


# --- what the scheduler would start ---


def test_a_disabled_channel_is_never_due(client):
    token = admin_token(client)
    channel(client, token, is_enabled=False)
    assert client.get("/api/admin/runs/due", headers=auth(token)).json() == []


def test_a_channel_with_no_cron_is_never_due(client):
    token = admin_token(client)
    channel(client, token, cron_full=None, cron_quick=None)
    assert client.get("/api/admin/runs/due", headers=auth(token)).json() == []


def test_a_channel_that_has_never_run_becomes_due(client):
    token = admin_token(client)
    source = channel(client, token, cron_full="* * * * *", cron_quick=None)

    due = client.get("/api/admin/runs/due", headers=auth(token)).json()
    assert [(d["source_id"], d["kind"]) for d in due] == [(source["id"], "full")]


def test_a_live_run_is_not_due_again(client):
    token = admin_token(client)
    source = channel(client, token, cron_full="* * * * *", cron_quick=None)
    start(client, token, source["id"])

    assert client.get("/api/admin/runs/due", headers=auth(token)).json() == []


def test_a_slot_already_covered_is_not_due(client):
    token = admin_token(client)
    source = channel(client, token, cron_full="* * * * *", cron_quick=None)
    run = start(client, token, source["id"])
    finish(client, token, run["id"], items_seen=1, items_ingested=1, coverage={"price": 1.0})

    # The run started after the most recent slot, so that slot is done.
    assert client.get("/api/admin/runs/due", headers=auth(token)).json() == []


def test_a_slot_long_past_is_let_go_rather_than_caught_up(client, event_loop, session_maker):
    """A crawl six hours late answers a question nobody is asking any more.

    Asked of the service with a fixed clock rather than through the endpoint: through it,
    whether the 03:00 slot is stale depends on what time the suite happens to run.
    """
    from datetime import UTC, datetime

    from app.features.runs.service import RunService

    token = admin_token(client)
    source = channel(client, token, cron_full="0 3 * * *", cron_quick=None)

    async def due_at(when: datetime) -> list[tuple[int, str]]:
        async with session_maker() as session:
            return [(d.source_id, d.kind) for d in await RunService(session).due(now=when)]

    # 05:00 — two hours after the slot, still worth doing.
    fresh = event_loop.run_until_complete(due_at(datetime(2026, 9, 22, 5, 0, tzinfo=UTC)))
    assert fresh == [(source["id"], "full")]

    # 14:00 — eleven hours after it. Let go; the next one is along tonight.
    stale = event_loop.run_until_complete(due_at(datetime(2026, 9, 22, 14, 0, tzinfo=UTC)))
    assert stale == []


# --- schedule config ---


def test_a_malformed_cron_is_refused_at_write_time(client):
    """Noticed only by the scheduler, it stops the channel in silence."""
    token = admin_token(client)
    shop, _ = setup_source(client, token)
    response = client.post(
        f"/api/admin/shops/{shop['id']}/sources",
        headers=auth(token),
        json={
            "slug": "rd-site",
            "access": "retail",
            "decode": "markup",
            "delivers_full": FULL,
            "cron_full": "every tuesday",
        },
    )
    assert response.status_code == 422


def test_a_quick_cron_needs_a_quick_pass(client):
    token = admin_token(client)
    shop, _ = setup_source(client, token)
    response = client.post(
        f"/api/admin/shops/{shop['id']}/sources",
        headers=auth(token),
        json={
            "slug": "rd-feed",
            "access": "retail",
            "decode": "xml",
            "delivers_full": FULL,
            "delivers_quick": [],
            "cron_quick": "0 * * * *",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "quick_cron_needs_a_quick_pass"


def test_runs_require_an_admin_token(client):
    assert client.get("/api/admin/runs").status_code == 401
    assert client.get("/api/admin/runs/due").status_code == 401
