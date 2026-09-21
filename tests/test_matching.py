"""Placing a listing in the catalogue, or saying exactly why it could not be placed."""

from tests.test_auth import ADMIN, CUSTOMER, auth, tokens
from tests.test_offers import ingest, post, setup_source


def admin_token(client) -> str:
    return tokens(client, ADMIN, panel="/admin")["access_token"]


def catalogue(client, token):
    """A brand with an alias, a category, and one variant carrying every identifier."""
    brand = post(client, token, "/api/admin/brands", {"slug": "apple", "canonical_name": "Apple"})
    post(
        client,
        token,
        f"/api/admin/brands/{brand['id']}/aliases",
        {"alias": "Apple", "kind": "spelling"},
    )
    category = post(client, token, "/api/admin/categories", {"slug": "phones", "name": "Phones"})
    variant = post(
        client,
        token,
        "/api/admin/variants",
        {
            "brand_id": brand["id"],
            "category_id": category["id"],
            "model": "iPhone 15 Pro",
        },
    )
    post(
        client,
        token,
        f"/api/admin/variants/{variant['id']}/gtins",
        {"value": "194253000001"},
    )
    post(
        client,
        token,
        f"/api/admin/variants/{variant['id']}/mpns",
        {"value": "MRXN3ZD/A"},
    )
    return brand, category, variant


def offer_from(client, token, source_id, payload, external_id="SKU-1"):
    return ingest(
        client,
        token,
        source_id,
        {"external_id": external_id, "market_code": "LV", "payload": payload},
    )["offer_id"]


def run_on(client, token, offer_id) -> dict:
    response = client.post(f"/api/admin/offers/{offer_id}/match", headers=auth(token))
    assert response.status_code == 200, response.text
    return response.json()


# --- the ladder ---


def test_a_barcode_is_the_first_rung(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    _, _, variant = catalogue(client, token)
    offer = offer_from(client, token, source["id"], {"name": "whatever", "ean": "194253000001"})

    outcome = run_on(client, token, offer)
    assert outcome["matched"] is True
    assert outcome["method"] == "gtin"
    assert outcome["variant_id"] == variant["id"]


def test_a_barcode_needs_no_brand(client):
    """Which is why it runs before the brand is resolved at all."""
    token = admin_token(client)
    _, source = setup_source(client, token)
    _, _, variant = catalogue(client, token)
    offer = offer_from(
        client, token, source["id"], {"name": "x", "ean": "194253000001", "brand": "Nokla"}
    )
    assert run_on(client, token, offer)["method"] == "gtin"


def test_brand_and_part_number(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    _, _, variant = catalogue(client, token)
    offer = offer_from(
        client,
        token,
        source["id"],
        {"name": "Apple iPhone", "brand": "Apple", "article": "mrxn3zd-a"},
    )

    outcome = run_on(client, token, offer)
    assert outcome["method"] == "brand_mpn"
    assert outcome["variant_id"] == variant["id"]


def test_brand_and_model(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    _, _, variant = catalogue(client, token)
    offer = offer_from(
        client,
        token,
        source["id"],
        {"name": "Apple iPhone 15 Pro", "brand": "Apple", "model": "iphone-15 PRO"},
    )

    outcome = run_on(client, token, offer)
    assert outcome["method"] == "brand_model"
    assert outcome["variant_id"] == variant["id"]


def test_the_evidence_says_what_the_link_is_made_of(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    catalogue(client, token)
    offer = offer_from(client, token, source["id"], {"name": "x", "ean": "194253000001"})
    run_on(client, token, offer)

    matches = client.get(f"/api/admin/offers/{offer}/matches", headers=auth(token)).json()
    assert matches[0]["evidence"] == {"signal": "gtin", "value": "194253000001"}
    assert matches[0]["confidence"] == "1.000"


# --- why it could not be placed ---


def test_nothing_to_go_on(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    catalogue(client, token)
    offer = offer_from(client, token, source["id"], {"name": "Some anonymous thing"})

    outcome = run_on(client, token, offer)
    assert outcome["matched"] is False
    assert outcome["reason"] == "no_signals"


def test_a_brand_nobody_knows(client):
    """Looking in the wrong drawer finds nothing correctly, so this is its own problem."""
    token = admin_token(client)
    _, source = setup_source(client, token)
    catalogue(client, token)
    offer = offer_from(
        client, token, source["id"], {"name": "Nokla phone", "brand": "Nokla", "model": "X1"}
    )

    outcome = run_on(client, token, offer)
    assert outcome["reason"] == "brand_unknown"
    # Nothing to offer: finishing this one starts with a person reading "Nokla".
    assert outcome["candidates"] == []


def test_a_brand_that_means_two_brands(client):
    """A separate problem from a brand nobody knows: the answers are already in hand."""
    token = admin_token(client)
    _, source = setup_source(client, token)
    catalogue(client, token)
    ids = []
    for slug in ("delta", "delta-tools"):
        brand = post(client, token, "/api/admin/brands", {"slug": slug, "canonical_name": "Delta"})
        ids.append(brand["id"])
        post(
            client,
            token,
            f"/api/admin/brands/{brand['id']}/aliases",
            {"alias": "Delta"},
        )

    offer = offer_from(
        client, token, source["id"], {"name": "Delta tap", "brand": "Delta", "model": "T1"}
    )
    outcome = run_on(client, token, offer)
    assert outcome["reason"] == "brand_ambiguous"
    # The whole point of the split: the choice is on the row, so it is one click and not
    # a search through the brand table.
    assert outcome["candidates"] == [
        {"brand_id": ids[0], "why": "brand_alias"},
        {"brand_id": ids[1], "why": "brand_alias"},
    ]


def test_a_brand_string_that_is_not_a_string(client):
    """Punctuation normalizes to nothing, which is the same work as an unknown brand."""
    token = admin_token(client)
    _, source = setup_source(client, token)
    catalogue(client, token)
    offer = offer_from(
        client, token, source["id"], {"name": "Thing", "brand": "---", "model": "X1"}
    )

    assert run_on(client, token, offer)["reason"] == "brand_unknown"


def test_a_barcode_that_missed_is_not_a_brand_problem(client):
    """The strongest rung needs no brand, so the brand cannot explain its failure.

    Found on real data: 520 listings, a barcode on 99.6% of them, every one reported as
    `brand_unknown` — which sends somebody to write brand aliases when what is missing is
    the product itself.
    """
    token = admin_token(client)
    _, source = setup_source(client, token)
    catalogue(client, token)
    offer = offer_from(
        client,
        token,
        source["id"],
        # A barcode nothing has, and a brand nobody has entered.
        {"name": "Nokla phone", "brand": "Nokla", "ean": "4006381333931"},
    )

    assert run_on(client, token, offer)["reason"] == "signals_unmatched"


def test_a_part_number_that_missed_still_is_a_brand_problem(client):
    """Both of the weaker rungs search inside a brand, so an unresolved one really stops
    them."""
    token = admin_token(client)
    _, source = setup_source(client, token)
    catalogue(client, token)
    offer = offer_from(
        client, token, source["id"], {"name": "Nokla phone", "brand": "Nokla", "mpn": "X1"}
    )

    assert run_on(client, token, offer)["reason"] == "brand_unknown"


def test_signals_the_catalogue_does_not_have(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    catalogue(client, token)
    offer = offer_from(
        client,
        token,
        source["id"],
        {"name": "Apple iPhone 99", "brand": "Apple", "model": "iPhone 99"},
    )

    assert run_on(client, token, offer)["reason"] == "signals_unmatched"


def test_two_variants_with_one_barcode_are_ambiguous(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    brand, category, first = catalogue(client, token)
    second = post(
        client,
        token,
        "/api/admin/variants",
        {"brand_id": brand["id"], "category_id": category["id"], "model": "iPhone 15 Pro Max"},
    )
    post(
        client,
        token,
        f"/api/admin/variants/{second['id']}/gtins",
        {"value": "194253000001"},
    )

    offer = offer_from(client, token, source["id"], {"name": "x", "ean": "194253000001"})
    outcome = run_on(client, token, offer)
    assert outcome["reason"] == "ambiguous"
    # The near misses come with it, so deciding is a choice rather than a search.
    assert {c["variant_id"] for c in outcome["candidates"]} == {first["id"], second["id"]}


def test_a_queued_offer_is_retried_rather_than_duplicated(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    catalogue(client, token)
    offer = offer_from(client, token, source["id"], {"name": "Anonymous"})

    run_on(client, token, offer)
    run_on(client, token, offer)

    queue = client.get("/api/admin/match-queue", headers=auth(token)).json()
    assert queue["total"] == 1
    assert queue["items"][0]["attempts"] == 2


# --- the invariant ---


def test_a_match_clears_the_queue_row(client):
    """An offer has an active match or a queue row, never both."""
    token = admin_token(client)
    _, source = setup_source(client, token)
    brand, category, _ = catalogue(client, token)
    offer = offer_from(
        client,
        token,
        source["id"],
        {"name": "Apple iPhone 99", "brand": "Apple", "model": "iPhone 99"},
    )
    run_on(client, token, offer)
    assert client.get("/api/admin/match-queue", headers=auth(token)).json()["total"] == 1

    # The catalogue gains what was missing, and the retry places it.
    made = post(
        client,
        token,
        "/api/admin/variants",
        {"brand_id": brand["id"], "category_id": category["id"], "model": "iPhone 99"},
    )
    outcome = run_on(client, token, offer)
    assert outcome["variant_id"] == made["id"]
    assert client.get("/api/admin/match-queue", headers=auth(token)).json()["total"] == 0


def test_re_matching_supersedes_rather_than_overwrites(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    brand, category, first = catalogue(client, token)
    offer = offer_from(client, token, source["id"], {"name": "x", "ean": "194253000001"})
    run_on(client, token, offer)

    other = post(
        client,
        token,
        "/api/admin/variants",
        {"brand_id": brand["id"], "category_id": category["id"], "model": "Something else"},
    )
    moved = client.put(
        f"/api/admin/offers/{offer}/match",
        headers=auth(token),
        json={"variant_id": other["id"], "note": "the feed was wrong"},
    )
    assert moved.status_code == 200

    history = client.get(f"/api/admin/offers/{offer}/matches", headers=auth(token)).json()
    assert len(history) == 2
    assert history[0]["variant_id"] == other["id"]
    assert history[0]["superseded_at"] is None
    # The previous opinion and its evidence survive.
    assert history[1]["variant_id"] == first["id"]
    assert history[1]["superseded_at"] is not None


def test_a_match_points_the_recorded_history_at_the_variant(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    _, _, variant = catalogue(client, token)
    offer = offer_from(
        client, token, source["id"], {"name": "x", "ean": "194253000001", "price": "100"}
    )

    before = client.get("/api/admin/price-history", headers=auth(token)).json()
    assert before["items"][0]["variant_id"] is None

    run_on(client, token, offer)
    after = client.get("/api/admin/price-history", headers=auth(token)).json()
    assert after["items"][0]["variant_id"] == variant["id"]


def test_unlinking_puts_it_back_and_clears_the_history_hint(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    catalogue(client, token)
    offer = offer_from(
        client, token, source["id"], {"name": "x", "ean": "194253000001", "price": "100"}
    )
    run_on(client, token, offer)

    dropped = client.delete(f"/api/admin/offers/{offer}/match", headers=auth(token))
    assert dropped.status_code == 204
    assert client.get("/api/admin/match-queue", headers=auth(token)).json()["total"] == 1

    history = client.get("/api/admin/price-history", headers=auth(token)).json()
    assert history["items"][0]["variant_id"] is None


# --- the number this was built for ---


def test_the_summary_says_what_is_in_the_way(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    catalogue(client, token)
    rows = {
        "matched": {"name": "x", "ean": "194253000001"},
        "no-brand": {"name": "Nokla", "brand": "Nokla", "model": "X1"},
        "missing": {"name": "Apple iPhone 99", "brand": "Apple", "model": "iPhone 99"},
        "blank": {"name": "Anonymous"},
    }
    for sku, payload in rows.items():
        offer_from(client, token, source["id"], payload, external_id=sku)

    report = client.post("/api/admin/matching/run", headers=auth(token)).json()
    assert report == {"attempted": 4, "matched": 1, "queued": 3}

    summary = client.get("/api/admin/match-queue/summary", headers=auth(token)).json()
    assert summary["offers"] == 4
    assert summary["matched_offers"] == 1
    assert summary["matched_share"] == 0.25
    assert summary["by_reason"] == {
        "brand_unknown": 1,
        "signals_unmatched": 1,
        "no_signals": 1,
    }


def test_the_run_skips_what_is_already_placed(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    catalogue(client, token)
    offer_from(client, token, source["id"], {"name": "x", "ean": "194253000001"})

    assert client.post("/api/admin/matching/run", headers=auth(token)).json()["matched"] == 1
    second = client.post("/api/admin/matching/run", headers=auth(token)).json()
    assert second == {"attempted": 0, "matched": 0, "queued": 0}


def test_matching_requires_an_admin_token(client):
    user_token = tokens(client, CUSTOMER)["access_token"]
    assert client.get("/api/admin/match-queue", headers=auth(user_token)).status_code == 401
    assert client.post("/api/admin/matching/run").status_code == 401
