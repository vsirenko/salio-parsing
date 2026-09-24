"""The queue a person works through: rows that name their listing, candidates compared axis
by axis, filters, snoozing, keeping a doubted match, and previews of what cannot be undone."""

from datetime import UTC, datetime, timedelta

from tests import test_judge
from tests.test_auth import auth
from tests.test_catalog import admin_token, post
from tests.test_judge import a_pro_max_under_the_pro, checking, doubts, match_reply
from tests.test_matching import (
    a_colour_axis,
    a_shop_we_can_build_from,
    a_storage_axis,
    offer_from,
    promote,
    run_on,
)

# The judge's stubbed client, borrowed: a fixture is found by name in the module using it.
judged = test_judge.judged


def queue(client, token, **params):
    response = client.get("/api/admin/match-queue", headers=auth(token), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def two_capacities_and_a_silent_listing(client, token):
    """`iPhone 15` at 128 and 256 GB, and a listing that names the model and no capacity."""
    _, source, category, brand = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])
    for external_id, storage, ean in (
        ("A-128", "128 GB", "4006381333931"),
        ("A-256", "256 GB", "0194253000001"),
    ):
        promote(
            client,
            token,
            offer_from(
                client,
                token,
                source["id"],
                {
                    "name": f"Apple iPhone 15 {storage}",
                    "brand": "Apple",
                    "model": "iPhone 15",
                    "ean": ean,
                    "attributes": {"storage": storage},
                },
                external_id=external_id,
            ),
        )
    silent = offer_from(
        client,
        token,
        source["id"],
        {"name": "Apple iPhone 15", "brand": "Apple", "model": "iPhone 15", "price": "700"},
        external_id="S-1",
    )
    run_on(client, token, silent)
    return source, category, brand, silent


def test_a_queue_row_names_its_listing_and_compares_its_candidates(client):
    token = admin_token(client)
    source, category, brand, silent = two_capacities_and_a_silent_listing(client, token)
    [row] = queue(client, token)["items"]
    assert row["offer_id"] == silent
    # Split on a capacity the listing does not state: nobody can choose, so not `ambiguous`.
    assert row["reason"] == "axis_unpublished"
    assert row["offer"]["title"] == "Apple iPhone 15"
    assert row["offer"]["shop"]["id"] == source["shop_id"]
    assert (row["offer"]["brand_raw"], row["offer"]["price"]) == ("Apple", "700.00")
    assert row["offer"]["category"] == {"id": category["id"], "name": "Phones"}
    assert row["brand"] == {"id": brand["id"], "name": "Apple"}
    assert row["model_key"] and row["siblings"] == 1

    shown = {c["variant_id"]: c for c in row["candidates"]}
    assert len(shown) == 2
    for candidate in shown.values():
        assert candidate["why"] == "model"
        assert candidate["model"] == "iPhone 15"
        assert candidate["brand"]["name"] == "Apple"
        assert candidate["offers_count"] == 1
        # The listing is silent on the axis the two entries are split on.
        [axis] = candidate["axes"]
        assert (axis["key"], axis["listing"], axis["agrees"]) == ("storage_mb", None, None)
    assert sorted(c["axes"][0]["entry"] for c in shown.values()) == ["128 GB", "256 GB"]

    one = client.get(f"/api/admin/match-queue/{silent}", headers=auth(token)).json()
    assert one == row
    trace = client.get(f"/api/admin/offers/{silent}/trace", headers=auth(token)).json()
    assert {c["variant_id"] for c in trace["queue"]["candidates"]} == set(shown)
    assert trace["queue"]["candidates"][0]["brand"]["name"] == "Apple"


def test_the_queue_filters_and_counts_what_one_new_entry_would_place(client):
    token = admin_token(client)
    _, source, category, brand = a_shop_we_can_build_from(client, token)

    def unmatched(external_id, model):
        offer = offer_from(
            client,
            token,
            source["id"],
            {"name": f"Apple {model}", "brand": "Apple", "model": model},
            external_id=external_id,
        )
        run_on(client, token, offer)
        return offer

    twins = [unmatched("X-1", "iPhone 99"), unmatched("X-2", "IPHONE-99")]
    single = unmatched("Y-1", "iPhone 98")
    stranger = offer_from(
        client, token, source["id"], {"name": "Nokia 3310", "brand": "Nokia"}, external_id="N-1"
    )
    run_on(client, token, stranger)

    rows = queue(client, token, sort="-siblings,offer_id")["items"]
    assert [(r["offer_id"], r["siblings"]) for r in rows] == [
        (twins[0], 2),
        (twins[1], 2),
        (single, 1),
        (stranger, 1),
    ]
    by_brand = queue(client, token, brand_id=brand["id"])["items"]
    assert sorted(r["offer_id"] for r in by_brand) == sorted([*twins, single])
    assert [r["offer_id"] for r in queue(client, token, reason="brand_unknown")["items"]] == [
        stranger
    ]
    assert queue(client, token, reason=["brand_unknown", "signals_unmatched"])["total"] == 4
    assert queue(client, token, shop_id=source["shop_id"])["total"] == 4
    assert queue(client, token, shop_id=999999)["total"] == 0
    assert queue(client, token, category_id=category["id"])["total"] == 4
    assert [r["offer_id"] for r in queue(client, token, search="3310")["items"]] == [stranger]
    assert [r["offer_id"] for r in queue(client, token, search="Y-1")["items"]] == [single]
    bad = client.get("/api/admin/match-queue", headers=auth(token), params={"sort": "reason"})
    assert bad.status_code == 422


def test_a_snoozed_row_is_hidden_until_then_and_the_sweep_leaves_it(client):
    token = admin_token(client)
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])
    a_colour_axis(client, token, category["id"])
    offer = offer_from(
        client,
        token,
        source["id"],
        {
            "name": "Apple iPhone 15 256 GB black",
            "brand": "Apple",
            "model": "iPhone 15",
            "ean": "4006381333931",
            "attributes": {"storage": "256 GB", "color": "black"},
        },
        external_id="A-1",
    )
    run_on(client, token, offer)
    url = f"/api/admin/match-queue/{offer}/snooze"

    past = client.post(
        url,
        headers=auth(token),
        json={"until": (datetime.now(UTC) - timedelta(hours=1)).isoformat()},
    )
    assert past.status_code == 422
    naive = client.post(url, headers=auth(token), json={"until": "2030-01-01T00:00:00"})
    assert naive.status_code == 422

    until = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    snoozed = client.post(url, headers=auth(token), json={"until": until})
    assert snoozed.status_code == 200, snoozed.text
    assert snoozed.json()["snoozed_until"] is not None
    assert queue(client, token)["total"] == 0
    assert [r["offer_id"] for r in queue(client, token, include_snoozed=True)["items"]] == [offer]

    swept = client.post("/api/admin/matching/promote", headers=auth(token)).json()
    assert swept["considered"] == 0

    back = client.delete(url, headers=auth(token))
    assert back.status_code == 200 and back.json()["snoozed_until"] is None
    assert queue(client, token)["total"] == 1
    assert (
        client.post(
            "/api/admin/match-queue/999999/snooze", headers=auth(token), json={"until": until}
        ).status_code
        == 404
    )


def test_a_kept_doubt_leaves_the_list_and_stays_by_its_signal(judged):
    client, stub = judged
    token = admin_token(client)
    offer, variant, source = a_pro_max_under_the_pro(client, token)
    stub.answers(match_reply(same=0.02))
    checking(client, token)

    page = client.get("/api/admin/matching/doubts", headers=auth(token)).json()
    assert page["total"] == 1
    [doubt] = page["items"]
    assert doubt["variant_title"] and doubt["offer"]["shop"]["id"] == source["shop_id"]
    assert doubt["offer"]["gtin"]
    assert (
        client.get(
            "/api/admin/matching/doubts", headers=auth(token), params={"method": "brand_model"}
        ).json()["total"]
        == 0
    )
    assert (
        client.get(
            "/api/admin/matching/doubts", headers=auth(token), params={"shop_id": source["shop_id"]}
        ).json()["total"]
        == 1
    )

    kept = client.post(f"/api/admin/matching/doubts/{offer}/keep", headers=auth(token))
    assert kept.status_code == 200, kept.text
    assert kept.json() == {
        "offer_id": offer,
        "variant_id": variant["id"],
        "method": "gtin",
        "decided_by": "human",
    }
    assert doubts(client, token) == []
    history = client.get(f"/api/admin/offers/{offer}/matches", headers=auth(token)).json()
    assert [(m["method"], m["decided_by"], m["superseded_at"] is None) for m in history] == [
        ("gtin", "human", True),
        ("gtin", "rule", False),
    ]
    # Once it is a person's, there is no rule's match left to keep.
    again = client.post(f"/api/admin/matching/doubts/{offer}/keep", headers=auth(token))
    assert (again.status_code, again.json()["error"]["code"]) == (409, "not_a_rule_match")


def test_a_promotion_can_be_previewed_and_keeps_nothing(client):
    token = admin_token(client)
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])
    a_colour_axis(client, token, category["id"])
    offer = offer_from(
        client,
        token,
        source["id"],
        {
            "name": "Apple iPhone 15 256 GB black",
            "brand": "Apple",
            "model": "iPhone 15",
            "ean": "4006381333931",
            "attributes": {"storage": "256 GB", "color": "black"},
        },
        external_id="A-1",
    )
    run_on(client, token, offer)

    one = client.post(
        f"/api/admin/offers/{offer}/promote", headers=auth(token), params={"dry_run": True}
    ).json()
    assert one["dry_run"] is True and one["matched"] is True
    assert one["created"]["id"] is None and one["created"]["model"] == "iPhone 15"
    swept = client.post(
        "/api/admin/matching/promote", headers=auth(token), params={"dry_run": True}
    ).json()
    assert (swept["dry_run"], swept["promoted"]) == (True, 1)
    assert [c["offer_id"] for c in swept["created"]] == [offer]
    assert swept["created"][0]["id"] is None

    # Nothing was written: no entry, the listing still queued, no trace of a promotion.
    assert client.get("/api/admin/variants", headers=auth(token)).json()["total"] == 0
    assert queue(client, token)["total"] == 1
    trail = client.get("/api/admin/audit", headers=auth(token)).json()["items"]
    previews = [e for e in trail if e["path"].endswith("/promote")]
    assert previews and all(not e["changes"] for e in previews)

    real = client.post("/api/admin/matching/promote", headers=auth(token)).json()
    assert real["promoted"] == 1 and real["created"][0]["id"] is not None
    assert client.get("/api/admin/variants", headers=auth(token)).json()["total"] == 1


def test_a_merge_can_be_previewed(client):
    token = admin_token(client)
    _, source, category, brand = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])
    a_colour_axis(client, token, category["id"])

    def listing(external_id, model):
        return offer_from(
            client,
            token,
            source["id"],
            {
                "name": f"Apple {model} 256 GB black",
                "brand": "Apple",
                "model": model,
                "ean": "4006381333931",
                "attributes": {"storage": "256 GB", "color": "black"},
            },
            external_id=external_id,
        )

    promote(client, token, listing("M-1", "PHONE WAVE 7C"))
    other = post(
        client,
        token,
        "/api/admin/variants",
        {"brand_id": brand["id"], "category_id": category["id"], "model": "Wave 7C"},
    )
    placed = client.put(
        f"/api/admin/offers/{listing('M-2', 'Wave 7C')}/match",
        headers=auth(token),
        json={"variant_id": other["id"]},
    )
    assert placed.status_code == 200, placed.text

    preview = client.post(
        "/api/admin/matching/merge", headers=auth(token), params={"dry_run": True}
    ).json()
    assert (preview["dry_run"], preview["found"], preview["merged"]) == (True, 1, 1)
    assert len(preview["pairs"]) == 1
    real = client.post("/api/admin/matching/merge", headers=auth(token)).json()
    assert (real["dry_run"], real["merged"], real["pairs"]) == (False, 1, preview["pairs"])


def test_the_judge_summary_counts_what_was_bought_and_what_was_not(judged):
    client, stub = judged
    token = admin_token(client)
    a_pro_max_under_the_pro(client, token)
    stub.answers(match_reply(same=0.02))
    checking(client, token)
    checking(client, token)

    summary = client.get("/api/admin/judge/summary", headers=auth(token)).json()
    for window in ("day", "week", "all_time"):
        assert (summary[window]["passes"], summary[window]["asked"]) == (2, 1)
        assert summary[window]["cached"] == 1
        assert summary[window]["by_kind"] == {"model_match": 1}
    assert summary["all_time"]["since"] is None


def test_repeated_passes_reach_every_queued_listing(client):
    """A pass takes the least recently tried first. In id order it took the same first
    `limit` every time, and the rest of the queue was never retried."""
    token = admin_token(client)
    _, source, _, _ = a_shop_we_can_build_from(client, token)
    offers = [
        offer_from(
            client,
            token,
            source["id"],
            {"name": f"Apple iPhone {n}", "brand": "Apple", "model": f"iPhone {n}"},
            external_id=f"R-{n}",
        )
        for n in (90, 91, 92)
    ]

    def attempts():
        rows = queue(client, token)["items"]
        return {row["offer_id"]: row["attempts"] for row in rows}

    for _ in range(3):
        report = client.post(
            "/api/admin/matching/run", headers=auth(token), params={"limit": 2}
        ).json()
        assert report["attempted"] == 2
    # Six attempts over three listings: every one of them twice, none left behind.
    assert attempts() == {offer: 2 for offer in offers}
