"""The judge's page: answers named and filtered, what became of them, reviews, forgetting,
what a pass would cost, and what was bought day by day."""

from datetime import UTC, datetime, timedelta

from app.core.config import settings
from tests import test_judge
from tests.test_auth import auth
from tests.test_judge import (
    a_delta_tap,
    a_pro_max_under_the_pro,
    checking,
    judging,
    match_reply,
    reply,
    two_deltas,
)
from tests.test_matching import admin_token, run_on
from tests.test_offers import setup_source

# The judge's stubbed client, borrowed: a fixture is found by name in the module using it.
judged = test_judge.judged


def verdicts(client, token, **params):
    response = client.get("/api/admin/judge/verdicts", headers=auth(token), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def a_doubted_check(client, stub, token):
    offer, variant, source = a_pro_max_under_the_pro(client, token)
    stub.answers(match_reply(same=0.02))
    checking(client, token)
    return offer, variant, source


def test_an_answer_names_its_options_and_the_listings_it_was_about(judged):
    client, stub = judged
    token = admin_token(client)
    offer, variant, source = a_doubted_check(client, stub, token)

    page = verdicts(client, token)
    assert page["total"] == 1
    [row] = page["items"]
    assert (row["kind"], row["outcome"]) == ("model_match", "doubt")
    assert set(row["answer"]) == {"choice", "confidence", "probabilities"}
    options = {option["key"]: option for option in row["options"]}
    assert options["same"]["label"] == "The entry's model"
    assert "Plus" in options["same"]["description"]
    assert row["choice_label"] == options[row["choice"]]["label"]
    [listing] = row["listings"]
    assert (listing["offer_id"], listing["state"], listing["variant_id"]) == (
        offer,
        "placed",
        variant["id"],
    )
    assert listing["shop"]["id"] == source["shop_id"]
    assert row["review"] is None and row["forgotten_at"] is None
    one = client.get(f"/api/admin/judge/verdicts/{row['id']}", headers=auth(token)).json()
    assert one == row


def test_a_brand_answer_names_the_brands_and_says_what_policy_made_of_it(judged):
    client, stub = judged
    token = admin_token(client)
    _, source = setup_source(client, token)
    (taps, _), _ = two_deltas(client, token)
    offer = a_delta_tap(client, token, source["id"])
    run_on(client, token, offer)
    stub.answers(reply("delta-taps", 0.97))
    judging(client, token)

    [row] = verdicts(client, token, kind="brand_choice")["items"]
    assert row["outcome"] == "accepted"
    labels = {option["key"]: option["label"] for option in row["options"]}
    assert labels == {
        "delta-taps": "Delta",
        "delta-tools": "Delta",
        "none_of_these": "None of these",
    }
    assert row["options"][0]["description"], "what the model was told is kept"
    assert [listing["offer_id"] for listing in row["listings"]] == [offer]


def test_the_list_filters_and_sorts(judged):
    client, stub = judged
    token = admin_token(client)
    a_doubted_check(client, stub, token)

    assert verdicts(client, token, outcome="doubt")["total"] == 1
    assert verdicts(client, token, outcome=["confirmed", "accepted"])["total"] == 0
    assert verdicts(client, token, kind=["brand_choice", "colour_choice"])["total"] == 0
    assert verdicts(client, token, no_match=True)["total"] == 0
    assert verdicts(client, token, search="pro max")["total"] == 1
    assert verdicts(client, token, search="galaxy")["total"] == 0
    # The stub answers `sibling` at 0.98.
    assert verdicts(client, token, confidence_min="0.99")["total"] == 0
    assert verdicts(client, token, confidence_min="0.9", confidence_max="0.99")["total"] == 1
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert verdicts(client, token, created_from=future)["total"] == 0
    assert verdicts(client, token, created_to=future)["total"] == 1
    assert verdicts(client, token, sort="-tokens")["total"] == 1
    bad = client.get("/api/admin/judge/verdicts", headers=auth(token), params={"sort": "kind"})
    assert bad.status_code == 422


def test_a_review_counts_in_its_confidence_bucket(judged):
    client, stub = judged
    token = admin_token(client)
    a_doubted_check(client, stub, token)
    [row] = verdicts(client, token)["items"]

    reviewed = client.post(
        f"/api/admin/judge/verdicts/{row['id']}/review",
        headers=auth(token),
        json={"correct": True, "note": "it is a Pro Max"},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["review"]["correct"] is True
    assert reviewed.json()["review"]["reviewed_by"]

    calibration = client.get(
        "/api/admin/judge/calibration", headers=auth(token), params={"kind": "model_match"}
    ).json()
    # The model check is bucketed by `same`, which is what its threshold compares.
    assert calibration["score"] == "same"
    assert calibration["threshold"] == settings.judge_doubt_below
    first = calibration["buckets"][0]
    assert (first["low"], first["answers"], first["reviewed"], first["correct"]) == (
        "0.00",
        1,
        1,
        1,
    )
    assert sum(bucket["answers"] for bucket in calibration["buckets"]) == 1

    # The latest word stands.
    client.post(
        f"/api/admin/judge/verdicts/{row['id']}/review",
        headers=auth(token),
        json={"correct": False},
    )
    again = client.get(
        "/api/admin/judge/calibration", headers=auth(token), params={"kind": "model_match"}
    ).json()
    assert (again["buckets"][0]["correct"], again["buckets"][0]["incorrect"]) == (0, 1)


def test_a_forgotten_answer_is_asked_again_and_still_counted(judged):
    client, stub = judged
    token = admin_token(client)
    a_doubted_check(client, stub, token)
    [row] = verdicts(client, token)["items"]

    pending = client.get("/api/admin/matching/judge/pending", headers=auth(token)).json()
    by_kind = {entry["kind"]: entry for entry in pending}
    assert (by_kind["model_match"]["eligible"], by_kind["model_match"]["to_ask"]) == (1, 0)

    gone = client.delete(f"/api/admin/judge/verdicts/{row['id']}", headers=auth(token))
    assert gone.status_code == 204
    assert verdicts(client, token, forgotten=True)["items"][0]["forgotten_at"]
    # Forgotten, so it doubts nothing any more.
    assert client.get("/api/admin/matching/doubts", headers=auth(token)).json()["total"] == 0

    pending = client.get("/api/admin/matching/judge/pending", headers=auth(token)).json()
    model = next(entry for entry in pending if entry["kind"] == "model_match")
    assert model["to_ask"] == 1
    assert model["estimated_input_tokens"] and model["estimated_output_tokens"]

    stub.answers(match_reply(same=0.9))
    report = checking(client, token)
    assert report["asked"] == 1
    assert verdicts(client, token)["total"] == 2
    usage = client.get("/api/admin/judge/usage", headers=auth(token)).json()
    [today] = [day for day in usage if day["kind"] == "model_match"]
    # Both were paid for, and the first pass's answer served the pending count, not a pass.
    assert today["asked"] == 2
    assert today["cached"] == 0
    assert today["input_tokens"] > 0
    assert client.delete("/api/admin/judge/verdicts/999999", headers=auth(token)).status_code == 404


def test_the_config_says_whether_the_judge_can_be_asked(judged):
    client, _ = judged
    token = admin_token(client)
    on = client.get("/api/admin/judge/config", headers=auth(token)).json()
    assert on["enabled"] is True
    assert (on["min_confidence"], on["doubt_below"]) == (
        settings.judge_min_confidence,
        settings.judge_doubt_below,
    )
    assert on["model"] == settings.typesafe_model


def test_without_a_key_the_config_says_so(client):
    token = admin_token(client)
    previous = settings.typesafe_api_key
    settings.typesafe_api_key = None
    try:
        off = client.get("/api/admin/judge/config", headers=auth(token)).json()
    finally:
        settings.typesafe_api_key = previous
    assert off["enabled"] is False
