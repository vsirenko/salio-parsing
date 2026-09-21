"""Asking an outside model which brand a listing means, and remembering the answer.

Nothing here reaches the network. The requests go through the real SDK and stop at a
transport inside the process, so the wire format, the question body and the decoding are
exercised for real — only the hop to TypeSafe is replaced.
"""

import json

import httpx2
import pytest
from pydantic import SecretStr
from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy

from app.core.config import settings
from app.features.judge.questions import NO_MATCH
from tests.test_auth import auth
from tests.test_matching import admin_token, offer_from, run_on
from tests.test_offers import post, setup_source

ANSWER = "brand_choice"


def reply(choice: str, confidence: float) -> dict:
    return {
        "model": "jev-1.13.0",
        "usage": {"input_tokens": 120, "output_tokens": 8},
        "answers": {
            ANSWER: {
                "type": "choice",
                "choice": choice,
                "confidence": confidence,
                "probabilities": {choice: confidence},
            }
        },
    }


class Stub:
    """Stands in for TypeSafe, and records what it was asked."""

    def __init__(self) -> None:
        self.replies: list = []
        self.asked: list[dict] = []

    def answers(self, *replies) -> "Stub":
        self.replies.extend(replies)
        return self

    def transport(self) -> httpx2.MockTransport:
        async def handle(request: httpx2.Request) -> httpx2.Response:
            self.asked.append(json.loads(request.content))
            assert self.replies, "the judge asked more questions than the test allowed"
            nxt = self.replies.pop(0)
            if isinstance(nxt, int):
                return httpx2.Response(nxt, json={"error": {"message": "unavailable"}})
            return httpx2.Response(200, json=nxt)

        return httpx2.MockTransport(handle)


@pytest.fixture
def judged(client):
    """The app with a judge that answers from a stub instead of from TypeSafe."""
    from app.api.deps import SessionDep, get_judge_service
    from app.features.judge.service import JudgeService
    from app.main import app

    previous = settings.typesafe_api_key
    settings.typesafe_api_key = SecretStr("test-key")
    stub = Stub()

    def build(session: SessionDep) -> JudgeService:
        return JudgeService(
            session,
            client_factory=lambda: AsyncTypeSafeClient(
                api_key="test-key",
                transport=stub.transport(),
                # Retrying is the SDK's business and it is tested there. Here it would
                # only mean a test asserting "one question" had to count attempts.
                retry=RetryPolicy(max_retries=0),
            ),
        )

    app.dependency_overrides[get_judge_service] = build
    try:
        yield client, stub
    finally:
        app.dependency_overrides.pop(get_judge_service, None)
        settings.typesafe_api_key = previous


def two_deltas(client, token):
    """Two unrelated companies trading as Delta, told apart by what they sell."""
    made = []
    for slug, category_slug, category_name, model in (
        ("delta-taps", "taps", "Taps", "T1"),
        ("delta-tools", "drills", "Drills", "D9"),
    ):
        brand = post(client, token, "/api/admin/brands", {"slug": slug, "canonical_name": "Delta"})
        post(client, token, f"/api/admin/brands/{brand['id']}/aliases", {"alias": "Delta"})
        category = post(
            client, token, "/api/admin/categories", {"slug": category_slug, "name": category_name}
        )
        variant = post(
            client,
            token,
            "/api/admin/variants",
            {"brand_id": brand["id"], "category_id": category["id"], "model": model},
        )
        made.append((brand, variant))
    return made


def a_delta_tap(client, token, source_id, external_id="SKU-1"):
    return offer_from(
        client,
        token,
        source_id,
        {"name": "Delta kitchen tap", "brand": "Delta", "model": "T1"},
        external_id=external_id,
    )


def judging(client, token, expect=200):
    response = client.post("/api/admin/matching/judge", headers=auth(token))
    assert response.status_code == expect, response.text
    return response.json()


# --- the question ---


def test_the_question_says_what_each_brand_is_known_for(judged):
    """The only true thing available about a brand here, and the whole basis for choosing."""
    client, stub = judged
    token = admin_token(client)
    _, source = setup_source(client, token)
    two_deltas(client, token)
    offer = a_delta_tap(client, token, source["id"])
    assert run_on(client, token, offer)["reason"] == "brand_ambiguous"

    stub.answers(reply("delta-taps", 0.97))
    judging(client, token)

    criteria = stub.asked[0]["questions"][ANSWER]["criteria"]
    assert "Taps" in criteria["delta-taps"]
    assert "Drills" in criteria["delta-tools"]
    # A Choice with no way out has to pick one of the options it was handed.
    assert NO_MATCH in criteria
    assert stub.asked[0]["state"]["listing_title"] == "Delta kitchen tap"


def test_a_brand_with_nothing_under_it_gets_no_invented_description(judged):
    client, stub = judged
    token = admin_token(client)
    _, source = setup_source(client, token)
    for slug in ("delta-taps", "delta-tools"):
        brand = post(client, token, "/api/admin/brands", {"slug": slug, "canonical_name": "Delta"})
        post(client, token, f"/api/admin/brands/{brand['id']}/aliases", {"alias": "Delta"})
    offer = a_delta_tap(client, token, source["id"])
    run_on(client, token, offer)

    stub.answers(reply("delta-taps", 0.40))
    judging(client, token)

    criteria = stub.asked[0]["questions"][ANSWER]["criteria"]
    assert criteria["delta-taps"] is None
    assert criteria["delta-tools"] is None


# --- what is done with the answer ---


def test_a_confident_answer_places_the_listing(judged):
    client, stub = judged
    token = admin_token(client)
    _, source = setup_source(client, token)
    (_, tap), _ = two_deltas(client, token)
    offer = a_delta_tap(client, token, source["id"])
    run_on(client, token, offer)

    stub.answers(reply("delta-taps", 0.97))
    report = judging(client, token)
    assert report["accepted"] == 1
    assert report["placed"] == 1

    matches = client.get(f"/api/admin/offers/{offer}/matches", headers=auth(token)).json()
    live = [m for m in matches if m["superseded_at"] is None]
    assert len(live) == 1
    assert live[0]["variant_id"] == tap["id"]
    # The rung that fired is still the rung that fired; what changes is who had the say.
    assert live[0]["method"] == "brand_model"
    assert live[0]["decided_by"] == "judge"
    assert live[0]["evidence"]["brand_via"] == "judge"
    assert live[0]["evidence"]["brand_confidence"] == 0.97


def test_a_weak_answer_is_recorded_and_not_acted_on(judged):
    """Typed output guarantees the interface, not the truth."""
    client, stub = judged
    token = admin_token(client)
    _, source = setup_source(client, token)
    two_deltas(client, token)
    offer = a_delta_tap(client, token, source["id"])
    run_on(client, token, offer)

    stub.answers(reply("delta-taps", 0.42))
    report = judging(client, token)
    assert report["accepted"] == 0
    assert report["unconfident"] == 1
    assert report["placed"] == 0

    queue = client.get("/api/admin/match-queue", headers=auth(token)).json()
    assert queue["items"][0]["reason"] == "brand_ambiguous"
    # Recorded even though it changed nothing: an answer nobody can inspect can only be
    # deleted, never argued with.
    assert client.get("/api/admin/judge/verdicts", headers=auth(token)).json()["total"] == 1


def test_neither_of_these_is_a_different_problem(judged):
    client, stub = judged
    token = admin_token(client)
    _, source = setup_source(client, token)
    two_deltas(client, token)
    offer = a_delta_tap(client, token, source["id"])
    run_on(client, token, offer)

    stub.answers(reply(NO_MATCH, 0.95))
    report = judging(client, token)
    assert report["no_match"] == 1
    assert report["placed"] == 0

    queue = client.get("/api/admin/match-queue", headers=auth(token)).json()
    # Not an unanswered choice any more: a brand nobody has, which is someone reading it.
    assert queue["items"][0]["reason"] == "brand_unknown"


# --- what it costs ---


def test_the_same_question_is_asked_once(judged):
    """The reason the store exists: the matcher retries the queue on every pass."""
    client, stub = judged
    token = admin_token(client)
    _, source = setup_source(client, token)
    two_deltas(client, token)
    offer = a_delta_tap(client, token, source["id"])
    run_on(client, token, offer)

    stub.answers(reply("delta-taps", 0.42))
    first = judging(client, token)
    assert (first["asked"], first["cached"]) == (1, 0)

    second = judging(client, token)
    assert (second["asked"], second["cached"]) == (0, 1)
    assert len(stub.asked) == 1


def test_two_shops_wording_it_identically_are_one_question(judged):
    client, stub = judged
    token = admin_token(client)
    _, source = setup_source(client, token)
    two_deltas(client, token)
    for external_id in ("SKU-1", "SKU-2"):
        run_on(client, token, a_delta_tap(client, token, source["id"], external_id))

    stub.answers(reply("delta-taps", 0.42))
    report = judging(client, token)
    assert report["considered"] == 2
    assert report["asked"] == 1
    assert len(stub.asked) == 1


def test_the_matcher_never_calls_out(judged):
    """Running the ladder stays offline; asking is its own explicit pass."""
    client, stub = judged
    token = admin_token(client)
    _, source = setup_source(client, token)
    two_deltas(client, token)
    offer = a_delta_tap(client, token, source["id"])

    run_on(client, token, offer)
    client.post("/api/admin/matching/run", headers=auth(token))
    assert stub.asked == []


def test_a_placed_listing_survives_a_re_run(judged):
    client, stub = judged
    token = admin_token(client)
    _, source = setup_source(client, token)
    two_deltas(client, token)
    offer = a_delta_tap(client, token, source["id"])
    run_on(client, token, offer)

    stub.answers(reply("delta-taps", 0.97))
    judging(client, token)

    # The verdict is an input to matching, so re-running finds it again without asking.
    assert run_on(client, token, offer)["matched"] is True
    assert len(stub.asked) == 1


# --- when it goes wrong ---


def test_a_service_failure_is_reported_and_not_stored(judged):
    client, stub = judged
    token = admin_token(client)
    _, source = setup_source(client, token)
    two_deltas(client, token)
    offer = a_delta_tap(client, token, source["id"])
    run_on(client, token, offer)

    stub.answers(503)
    report = judging(client, token)
    assert report["failed"] == 1
    assert report["asked"] == 0
    assert report["error"]

    # A stored failure would read as an answer on the next pass, so it is asked again.
    assert client.get("/api/admin/judge/verdicts", headers=auth(token)).json()["total"] == 0
    stub.answers(reply("delta-taps", 0.97))
    assert judging(client, token)["placed"] == 1


def test_judging_is_off_without_a_key(client):
    """The key is the only switch. A flag beside it could disagree with it.

    Forced off rather than assumed off: settings are loaded from the developer's own
    `.env`, so a test that reads it passes or fails depending on whose machine runs it.
    """
    previous = settings.typesafe_api_key
    settings.typesafe_api_key = None
    try:
        token = admin_token(client)
        body = client.post("/api/admin/matching/judge", headers=auth(token)).json()
        assert body["error"]["code"] == "judge_disabled"
    finally:
        settings.typesafe_api_key = previous


def test_judging_requires_an_admin_token(client):
    assert client.post("/api/admin/matching/judge").status_code == 401
    assert client.get("/api/admin/judge/verdicts").status_code == 401
