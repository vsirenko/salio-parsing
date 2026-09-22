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


# --- starting the catalogue ---


def promote(client, token, offer_id, expect=200):
    response = client.post(f"/api/admin/offers/{offer_id}/promote", headers=auth(token))
    assert response.status_code == expect, response.text
    return response.json()


def a_shop_we_can_build_from(client, token):
    """A trusted channel that says what it collects, and a brand we know."""
    shop, source = setup_source(client, token)
    category = post(client, token, "/api/admin/categories", {"slug": "phones", "name": "Phones"})
    client.patch(
        f"/api/admin/sources/{source['id']}",
        headers=auth(token),
        json={"category_id": category["id"], "trust": "high"},
    )
    brand = post(client, token, "/api/admin/brands", {"slug": "apple", "canonical_name": "Apple"})
    post(client, token, f"/api/admin/brands/{brand['id']}/aliases", {"alias": "Apple"})
    return shop, source, category, brand


def a_storage_axis(client, token, category_id):
    attribute = post(
        client,
        token,
        "/api/admin/attributes",
        {
            "key": "storage_mb",
            "name": "Storage",
            "value_type": "number",
            "unit_dimension": "MB",
            "scale": 0,
        },
    )
    post(
        client,
        token,
        f"/api/admin/categories/{category_id}/attributes",
        {"attribute_id": attribute["id"], "identity_bearing": True},
    )
    return attribute


def test_a_listing_becomes_the_variant_it_was_looking_for(client):
    token = admin_token(client)
    _, source, _, _ = a_shop_we_can_build_from(client, token)
    offer = offer_from(
        client,
        token,
        source["id"],
        {"name": "Apple iPhone 15", "brand": "Apple", "model": "iPhone 15", "ean": "4006381333931"},
    )
    assert run_on(client, token, offer)["reason"] == "signals_unmatched"

    outcome = promote(client, token, offer)
    # Not a new kind of match: the variant is made and the ordinary ladder places it.
    assert (outcome["matched"], outcome["method"]) == (True, "gtin")
    assert client.get("/api/admin/variants", headers=auth(token)).json()["total"] == 1


def test_a_second_shop_lands_on_what_the_first_one_made(client):
    """The whole point. Two shops, one product, one catalogue entry."""
    token = admin_token(client)
    shop, first, _, _ = a_shop_we_can_build_from(client, token)
    second = post(
        client,
        token,
        f"/api/admin/shops/{shop['id']}/sources",
        {
            "slug": "rd-other",
            "access": "wholesale",
            "decode": "xml",
            "delivers_full": ["catalogue", "price", "availability"],
            "trust": "high",
        },
    )
    body = {
        "name": "Apple iPhone 15",
        "brand": "Apple",
        "model": "iPhone 15",
        "ean": "4006381333931",
    }
    mine = offer_from(client, token, first["id"], body, external_id="A-1")
    theirs = offer_from(client, token, second["id"], body, external_id="B-1")

    promote(client, token, mine)
    assert run_on(client, token, theirs)["matched"] is True
    assert client.get("/api/admin/variants", headers=auth(token)).json()["total"] == 1


def test_capacities_of_one_model_are_variants_of_one_product(client):
    """A model string names a family, not a buyable thing."""
    token = admin_token(client)
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])

    for external_id, ean, size in (
        ("A-1", "4006381333931", "256 GB"),
        ("A-2", "5902983617747", "512 GB"),
    ):
        offer = offer_from(
            client,
            token,
            source["id"],
            {
                "name": f"Apple iPhone 15 {size}",
                "brand": "Apple",
                "model": "iPhone 15",
                "ean": ean,
                "attributes": {"storage": size},
            },
            external_id=external_id,
        )
        promote(client, token, offer)

    variants = client.get("/api/admin/variants", headers=auth(token)).json()
    products = client.get("/api/admin/products", headers=auth(token)).json()
    assert variants["total"] == 2
    assert products["total"] == 1
    assert {v["product_id"] for v in variants["items"]} == {products["items"][0]["id"]}


def test_a_model_that_agrees_but_a_capacity_that_does_not_is_not_a_match(client):
    """What went wrong before: fifteen listings and a thousand euros as one entry."""
    token = admin_token(client)
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])

    small = offer_from(
        client,
        token,
        source["id"],
        {
            "name": "Apple iPhone 15 256 GB",
            "brand": "Apple",
            "model": "iPhone 15",
            "ean": "4006381333931",
            "attributes": {"storage": "256 GB"},
        },
        external_id="A-1",
    )
    promote(client, token, small)

    # Same model, no barcode to fall back on, a different capacity.
    big = offer_from(
        client,
        token,
        source["id"],
        {
            "name": "Apple iPhone 15 512 GB",
            "brand": "Apple",
            "model": "iPhone 15",
            "attributes": {"storage": "512 GB"},
        },
        external_id="A-2",
    )
    assert run_on(client, token, big)["matched"] is False


def test_a_candidate_nothing_can_check_is_low_confidence(client):
    """Not a match and not a miss — the third answer `low_confidence` was waiting for.

    The listing brought a capacity and the candidate has none recorded, so nothing can
    confirm or deny that they are the same thing.
    """
    token = admin_token(client)
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])

    # Promoted from a listing that said nothing about capacity, so the variant carries none.
    promote(
        client,
        token,
        offer_from(
            client,
            token,
            source["id"],
            {
                "name": "Apple iPhone 15",
                "brand": "Apple",
                "model": "iPhone 15",
                "ean": "4006381333931",
            },
            external_id="A-1",
        ),
    )
    # This one knows its capacity, and there is nothing on the candidate to check it against.
    described = offer_from(
        client,
        token,
        source["id"],
        {
            "name": "Apple iPhone 15 512 GB",
            "brand": "Apple",
            "model": "iPhone 15",
            "attributes": {"storage": "512 GB"},
        },
        external_id="A-2",
    )
    outcome = run_on(client, token, described)
    assert outcome["reason"] == "low_confidence"
    assert outcome["candidates"]


def test_a_listing_with_nothing_to_check_still_matches_on_the_model(client):
    """The check applies when there is something to check with. Without it the rung would
    never fire until every category and every shop were furnished."""
    token = admin_token(client)
    _, source, _, _ = a_shop_we_can_build_from(client, token)
    promote(
        client,
        token,
        offer_from(
            client,
            token,
            source["id"],
            {
                "name": "Apple iPhone 15",
                "brand": "Apple",
                "model": "iPhone 15",
                "ean": "4006381333931",
            },
            external_id="A-1",
        ),
    )
    plain = offer_from(
        client,
        token,
        source["id"],
        {"name": "Apple iPhone 15", "brand": "Apple", "model": "iPhone 15"},
        external_id="A-2",
    )
    outcome = run_on(client, token, plain)
    assert (outcome["matched"], outcome["method"]) == (True, "brand_model")


# --- the bar a listing has to clear ---


def test_a_sweep_takes_only_what_carries_a_barcode(client):
    token = admin_token(client)
    _, source, _, _ = a_shop_we_can_build_from(client, token)
    offer_from(
        client, token, source["id"], {"name": "Apple thing", "brand": "Apple", "model": "Thing"}
    )
    client.post("/api/admin/matching/run", headers=auth(token))

    report = client.post("/api/admin/matching/promote", headers=auth(token)).json()
    assert (report["promoted"], report["reasons"]) == (0, {"no_barcode": 1})


def test_a_shop_title_is_not_a_model(client):
    """A catalogue entry named after a sentence cannot be searched for and groups with
    nothing, while looking like a real product."""
    token = admin_token(client)
    _, source, _, _ = a_shop_we_can_build_from(client, token)
    offer = offer_from(
        client,
        token,
        source["id"],
        {
            "name": "Tālrunis Apple iPhone 15 6,1 collas Dual SIM 5G melns",
            "brand": "Apple",
            "ean": "4006381333931",
        },
    )
    assert promote(client, token, offer, expect=422)["error"]["code"] == "no_model"


def test_an_untrusted_channel_does_not_start_the_catalogue(client):
    token = admin_token(client)
    _, source, _, _ = a_shop_we_can_build_from(client, token)
    client.patch(f"/api/admin/sources/{source['id']}", headers=auth(token), json={"trust": "low"})
    offer_from(
        client,
        token,
        source["id"],
        {"name": "x", "brand": "Apple", "model": "M", "ean": "4006381333931"},
    )
    client.post("/api/admin/matching/run", headers=auth(token))

    report = client.post("/api/admin/matching/promote", headers=auth(token)).json()
    assert report["reasons"] == {"source_not_trusted": 1}


def test_a_channel_that_does_not_say_its_category(client):
    token = admin_token(client)
    _, source = setup_source(client, token)
    client.patch(f"/api/admin/sources/{source['id']}", headers=auth(token), json={"trust": "high"})
    brand = post(client, token, "/api/admin/brands", {"slug": "apple", "canonical_name": "Apple"})
    post(client, token, f"/api/admin/brands/{brand['id']}/aliases", {"alias": "Apple"})
    offer = offer_from(
        client,
        token,
        source["id"],
        {"name": "x", "brand": "Apple", "model": "M", "ean": "4006381333931"},
    )
    assert promote(client, token, offer, expect=422)["error"]["code"] == "category_unknown"


def test_a_brand_nobody_entered_cannot_start_an_entry(client):
    token = admin_token(client)
    _, source, _, _ = a_shop_we_can_build_from(client, token)
    offer = offer_from(
        client,
        token,
        source["id"],
        {"name": "x", "brand": "Nokla", "model": "M", "ean": "4006381333931"},
    )
    assert promote(client, token, offer, expect=422)["error"]["code"] == "brand_unresolved"


def test_the_origin_of_a_variant_is_in_the_trail(client):
    """Nothing on the row says which listing it was built from."""
    token = admin_token(client)
    _, source, _, _ = a_shop_we_can_build_from(client, token)
    offer = offer_from(
        client,
        token,
        source["id"],
        {"name": "x", "brand": "Apple", "model": "M", "ean": "4006381333931"},
    )
    promote(client, token, offer)

    entries = client.get("/api/admin/audit", headers=auth(token)).json()["items"]
    origin = next(e for e in entries if e["changes"].get("created_from_offer"))
    assert origin["target_type"] == "variant"
    assert origin["changes"]["created_from_offer"] == offer


# --- a part number is not always the thing you buy ---


def test_a_part_number_that_covers_two_capacities_does_not_merge_them(client):
    """Measured on bigbox: `CPH2865` is the Oppo Reno16 5G at 256 GB and at 512 GB alike,
    and five of twenty matches on this rung had pulled two capacities onto one variant."""
    token = admin_token(client)
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])

    promote(
        client,
        token,
        offer_from(
            client,
            token,
            source["id"],
            {
                "name": "Apple iPhone 15 256 GB",
                "brand": "Apple",
                "model": "iPhone 15",
                "mpn": "CPH2865",
                "ean": "4006381333931",
                "attributes": {"storage": "256 GB"},
            },
            external_id="A-1",
        ),
    )

    # The same part number, a barcode nothing has yet, and twice the capacity.
    bigger = offer_from(
        client,
        token,
        source["id"],
        {
            "name": "Apple iPhone 15 512 GB",
            "brand": "Apple",
            "model": "iPhone 15",
            "mpn": "CPH2865",
            "ean": "5902983617747",
            "attributes": {"storage": "512 GB"},
        },
        external_id="A-2",
    )
    assert run_on(client, token, bigger)["matched"] is False


def test_a_part_number_with_nothing_to_check_is_still_believed(client):
    """Where this rung differs from the model rung below it. A model string names a family
    on purpose; a part number is meant to name the thing you buy, so it is believed until
    something contradicts it — otherwise the rung would stop firing on every category that
    has no axes yet."""
    token = admin_token(client)
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])

    promote(
        client,
        token,
        offer_from(
            client,
            token,
            source["id"],
            {
                "name": "Apple iPhone 15",
                "brand": "Apple",
                "model": "iPhone 15",
                "mpn": "MRXN3ZD/A",
                "ean": "4006381333931",
            },
            external_id="A-1",
        ),
    )
    # It states a capacity; the variant has none recorded, so there is nothing to compare.
    described = offer_from(
        client,
        token,
        source["id"],
        {
            "name": "Apple iPhone 15 512 GB",
            "brand": "Apple",
            "model": "iPhone something else",
            "mpn": "MRXN3ZD/A",
            "attributes": {"storage": "512 GB"},
        },
        external_id="A-2",
    )
    outcome = run_on(client, token, described)
    assert (outcome["matched"], outcome["method"]) == (True, "brand_mpn")


# --- keeping a barcode the match was made without ---


def gtins_of(client, token, variant_id) -> set[str]:
    response = client.get(f"/api/admin/variants/{variant_id}/gtins", headers=auth(token))
    assert response.status_code == 200, response.text
    return {row["gtin"] for row in response.json()}


def test_a_confirmed_model_match_keeps_the_barcode_it_was_made_without(client):
    """Of 207 barcodes the two collected shops share, 88 were on no variant: the listings
    carrying them matched on the model, and the barcode was tried, missed and dropped."""
    token = admin_token(client)
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])

    first = offer_from(
        client,
        token,
        source["id"],
        {
            "name": "Apple iPhone 15 256 GB",
            "brand": "Apple",
            "model": "iPhone 15",
            "ean": "4006381333931",
            "attributes": {"storage": "256 GB"},
        },
        external_id="A-1",
    )
    variant_id = promote(client, token, first)["variant_id"]

    # Another shop's barcode for the same phone. The capacity confirms the model.
    theirs = offer_from(
        client,
        token,
        source["id"],
        {
            "name": "Apple iPhone 15 256 GB",
            "brand": "Apple",
            "model": "iPhone 15",
            "ean": "5902983617747",
            "attributes": {"storage": "256 GB"},
        },
        external_id="A-2",
    )
    assert run_on(client, token, theirs)["method"] == "brand_model"
    assert gtins_of(client, token, variant_id) == {"4006381333931", "5902983617747"}


def test_the_kept_barcode_is_what_places_the_next_listing(client):
    """The point of keeping it: the same work is not redone on every pass."""
    token = admin_token(client)
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])

    body = {
        "name": "Apple iPhone 15 256 GB",
        "brand": "Apple",
        "model": "iPhone 15",
        "attributes": {"storage": "256 GB"},
    }
    promote(
        client,
        token,
        offer_from(
            client,
            token,
            source["id"],
            {**body, "ean": "4006381333931"},
            external_id="A-1",
        ),
    )
    run_on(
        client,
        token,
        offer_from(
            client, token, source["id"], {**body, "ean": "5902983617747"}, external_id="A-2"
        ),
    )

    # A third listing states only that barcode. Before it was kept, this was a miss.
    bare = offer_from(
        client,
        token,
        source["id"],
        {"name": "some phone", "ean": "5902983617747"},
        external_id="A-3",
    )
    outcome = run_on(client, token, bare)
    assert (outcome["matched"], outcome["method"]) == (True, "gtin")


def test_an_unconfirmed_model_match_does_not_keep_the_barcode(client):
    """A model match is a conclusion, not proof. Writing its barcode onto the variant turns
    the conclusion into proof, and a wrong one could not be argued with afterwards."""
    token = admin_token(client)
    _, source, _, _ = a_shop_we_can_build_from(client, token)

    first = offer_from(
        client,
        token,
        source["id"],
        {"name": "Apple iPhone 15", "brand": "Apple", "model": "iPhone 15", "ean": "4006381333931"},
        external_id="A-1",
    )
    variant_id = promote(client, token, first)["variant_id"]

    # Nothing on either side to check the model against.
    theirs = offer_from(
        client,
        token,
        source["id"],
        {"name": "Apple iPhone 15", "brand": "Apple", "model": "iPhone 15", "ean": "5902983617747"},
        external_id="A-2",
    )
    assert run_on(client, token, theirs)["method"] == "brand_model"
    assert gtins_of(client, token, variant_id) == {"4006381333931"}


# --- an entry learns what its listings know ---


def a_colour_axis(client, token, category_id):
    attribute = post(
        client,
        token,
        "/api/admin/attributes",
        {"key": "color", "name": "Colour", "value_type": "enum"},
    )
    post(
        client,
        token,
        f"/api/admin/categories/{category_id}/attributes",
        {"attribute_id": attribute["id"], "identity_bearing": True},
    )
    for canonical in ("black", "blue"):
        value = post(
            client,
            token,
            f"/api/admin/attributes/{attribute['id']}/values",
            {"canonical": canonical},
        )
        post(
            client,
            token,
            f"/api/admin/attributes/values/{value['id']}/aliases",
            {"alias": canonical, "language": "en"},
        )
    return attribute


def test_a_match_fills_in_an_axis_the_entry_never_had(client):
    """A catalogue entry made from a shop that states no colour had none, for good — and the
    comparison only weighs axes both sides carry, so colour could separate nothing. One
    `Nokia 3210` held the black, the blue and the gold."""
    token = admin_token(client)
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])
    a_colour_axis(client, token, category["id"])

    # The entry is made from a listing that says nothing about colour.
    plain = offer_from(
        client,
        token,
        source["id"],
        {
            "name": "Apple iPhone 15 256 GB",
            "brand": "Apple",
            "model": "iPhone 15",
            "ean": "4006381333931",
            "attributes": {"storage": "256 GB"},
        },
        external_id="A-1",
    )
    variant_id = promote(client, token, plain)["variant_id"]

    # The same phone from a shop that does state colour, matching by barcode.
    described = offer_from(
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
        external_id="A-2",
    )
    assert run_on(client, token, described)["method"] == "gtin"

    axes = client.get(f"/api/admin/variants/{variant_id}/attributes", headers=auth(token)).json()
    assert any(a.get("value_id") for a in axes), "the entry learned a colour it did not have"


def test_the_learned_axis_then_keeps_another_colour_out(client):
    """The point of learning it. Before, a blue phone agreeing on capacity joined the black
    one and the entry held both."""
    token = admin_token(client)
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])
    a_colour_axis(client, token, category["id"])

    body = {"brand": "Apple", "model": "iPhone 15", "attributes": {"storage": "256 GB"}}
    promote(
        client,
        token,
        offer_from(
            client,
            token,
            source["id"],
            {**body, "name": "Apple iPhone 15 256 GB", "ean": "4006381333931"},
            external_id="A-1",
        ),
    )
    run_on(
        client,
        token,
        offer_from(
            client,
            token,
            source["id"],
            {
                **body,
                "name": "iPhone 15 black",
                "ean": "4006381333931",
                "attributes": {"storage": "256 GB", "color": "black"},
            },
            external_id="A-2",
        ),
    )

    # A different colour, same model and capacity, no barcode of its own to fall back on.
    blue = offer_from(
        client,
        token,
        source["id"],
        {**body, "name": "iPhone 15 blue", "attributes": {"storage": "256 GB", "color": "blue"}},
        external_id="A-3",
    )
    assert run_on(client, token, blue)["matched"] is False


def test_a_match_never_overwrites_an_axis_that_is_already_there(client):
    """A shop states 512 GB for a phone whose own title reads `4/128GB`. Letting whichever
    listing arrived second replace the first would make the catalogue depend on crawl order.
    """
    token = admin_token(client)
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])

    first = offer_from(
        client,
        token,
        source["id"],
        {
            "name": "Apple iPhone 15 256 GB",
            "brand": "Apple",
            "model": "iPhone 15",
            "ean": "4006381333931",
            "attributes": {"storage": "256 GB"},
        },
        external_id="A-1",
    )
    variant_id = promote(client, token, first)["variant_id"]

    # Same barcode, and a capacity the other shop got wrong.
    wrong = offer_from(
        client,
        token,
        source["id"],
        {
            "name": "Apple iPhone 15",
            "brand": "Apple",
            "model": "iPhone 15",
            "ean": "4006381333931",
            "attributes": {"storage": "512 GB"},
        },
        external_id="A-2",
    )
    run_on(client, token, wrong)

    axes = client.get(f"/api/admin/variants/{variant_id}/attributes", headers=auth(token)).json()
    stored = next(a for a in axes if a["value_num"] is not None)
    assert float(stored["value_num"]) == 256 * 1024, "the first answer stood"


def test_a_barcode_is_kept_only_when_every_axis_was_weighed(client):
    """Agreeing on capacity while the entry has no colour to disagree with is not the same
    as agreeing. Treated as one, it put a black phone's barcode on a blue one's entry —
    permanently, and at confidence 1.00 from then on."""
    token = admin_token(client)
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])
    a_colour_axis(client, token, category["id"])

    # The entry knows a capacity and nothing about colour.
    plain = offer_from(
        client,
        token,
        source["id"],
        {
            "name": "Apple iPhone 15 256 GB",
            "brand": "Apple",
            "model": "iPhone 15",
            "ean": "4006381333931",
            "attributes": {"storage": "256 GB"},
        },
        external_id="A-1",
    )
    variant_id = promote(client, token, plain)["variant_id"]

    # A listing that states a colour, and a barcode of its own. It matches on the model and
    # the capacity — but the colour went unweighed, so its barcode is not worth keeping.
    coloured = offer_from(
        client,
        token,
        source["id"],
        {
            "name": "Apple iPhone 15 256 GB black",
            "brand": "Apple",
            "model": "iPhone 15",
            "ean": "5902983617747",
            "attributes": {"storage": "256 GB", "color": "black"},
        },
        external_id="A-2",
    )
    assert run_on(client, token, coloured)["method"] == "brand_model"
    assert gtins_of(client, token, variant_id) == {"4006381333931"}, "the barcode was not kept"


def test_a_silent_axis_is_not_agreement(client):
    """Two shops that state no colour make a red and a black phone look identical, and the
    weaker reading counted that silence as agreement: everything the listing carried was
    weighed, because it carried nothing that could disagree. The bar is what the *category*
    says tells its products apart."""
    token = admin_token(client)
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])
    a_colour_axis(client, token, category["id"])

    # An entry from a shop that states capacity and never colour.
    silent = offer_from(
        client,
        token,
        source["id"],
        {
            "name": "Apple iPhone 15 256 GB",
            "brand": "Apple",
            "model": "iPhone 15",
            "ean": "4006381333931",
            "attributes": {"storage": "256 GB"},
        },
        external_id="A-1",
    )
    variant_id = promote(client, token, silent)["variant_id"]

    # Another listing from the same silent shop: same model, same capacity, and in truth a
    # different colour that neither side can say. It still matches — there is nothing to
    # separate them on — but its barcode must not be written onto the entry, because that
    # is what turns the guess into proof for everything that comes after.
    also_silent = offer_from(
        client,
        token,
        source["id"],
        {
            "name": "Apple iPhone 15 256 GB",
            "brand": "Apple",
            "model": "iPhone 15",
            "ean": "5902983617747",
            "attributes": {"storage": "256 GB"},
        },
        external_id="A-2",
    )
    assert run_on(client, token, also_silent)["method"] == "brand_model"
    assert gtins_of(client, token, variant_id) == {"4006381333931"}, "the barcode was not kept"


def test_a_category_with_no_declared_axes_keeps_the_older_bar(client):
    """Requiring nothing would make every match complete, which is the opposite of the
    intent. Where a category declares no identity axes, what the listing carried stands."""
    token = admin_token(client)
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])
    client.patch(
        f"/api/admin/categories/{category['id']}/attributes/"
        + str(
            client.get(
                f"/api/admin/attributes/by-category/{category['id']}", headers=auth(token)
            ).json()[0]["attribute_id"]
        ),
        headers=auth(token),
        json={"identity_bearing": False},
    )

    first = offer_from(
        client,
        token,
        source["id"],
        {
            "name": "Apple iPhone 15 256 GB",
            "brand": "Apple",
            "model": "iPhone 15",
            "ean": "4006381333931",
            "attributes": {"storage": "256 GB"},
        },
        external_id="A-1",
    )
    variant_id = promote(client, token, first)["variant_id"]

    second = offer_from(
        client,
        token,
        source["id"],
        {
            "name": "Apple iPhone 15 256 GB",
            "brand": "Apple",
            "model": "iPhone 15",
            "ean": "5902983617747",
            "attributes": {"storage": "256 GB"},
        },
        external_id="A-2",
    )
    assert run_on(client, token, second)["method"] == "brand_model"
    assert gtins_of(client, token, variant_id) == {"4006381333931", "5902983617747"}


# --- a shop that publishes no barcode at all ---


def test_a_complete_identity_may_start_an_entry_without_a_barcode(client):
    """A barcode was the bar for as long as it was the only thing two shops could agree on.
    It left a whole shop unable to contribute: 1a.lv publishes none, and 27 of its listings
    sat fully read — brand, model, capacity, colour — and invisible to the catalogue."""
    token = admin_token(client)
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])
    a_colour_axis(client, token, category["id"])

    offer_from(
        client,
        token,
        source["id"],
        {
            "name": "Apple iPhone 15 256 GB black",
            "brand": "Apple",
            "model": "iPhone 15",
            "attributes": {"storage": "256 GB", "color": "black"},
        },
        external_id="A-1",
    )
    # Through the sweep, which is where the bar lives — a listing promoted by hand is a
    # person saying so and has never had one.
    client.post("/api/admin/matching/run", headers=auth(token))
    report = client.post("/api/admin/matching/promote", headers=auth(token)).json()
    assert (report["promoted"], report["reasons"]) == (1, {}), report
    assert client.get("/api/admin/variants", headers=auth(token)).json()["total"] == 1


def test_an_incomplete_identity_without_a_barcode_still_waits(client):
    """The second bar is not a weaker one: it asks for every axis the category calls
    identity-bearing. A listing that names one of two is a guess wearing a catalogue's
    authority, which is what the barcode bar was written against."""
    token = admin_token(client)
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])
    a_colour_axis(client, token, category["id"])

    offer_from(
        client,
        token,
        source["id"],
        {
            "name": "Apple iPhone 15 256 GB",
            "brand": "Apple",
            "model": "iPhone 15",
            "attributes": {"storage": "256 GB"},
        },
        external_id="A-1",
    )
    client.post("/api/admin/matching/run", headers=auth(token))
    report = client.post("/api/admin/matching/promote", headers=auth(token)).json()
    assert (report["promoted"], report["reasons"]) == (0, {"no_barcode": 1}), report


def test_a_category_with_no_declared_axes_keeps_the_barcode_bar(client):
    """Requiring nothing would let anything through, which is the opposite of the intent."""
    token = admin_token(client)
    _, source, _, _ = a_shop_we_can_build_from(client, token)

    offer_from(
        client,
        token,
        source["id"],
        {
            "name": "Apple iPhone 15 256 GB black",
            "brand": "Apple",
            "model": "iPhone 15",
            "attributes": {"storage": "256 GB", "color": "black"},
        },
        external_id="A-1",
    )
    client.post("/api/admin/matching/run", headers=auth(token))
    report = client.post("/api/admin/matching/promote", headers=auth(token)).json()
    assert (report["promoted"], report["reasons"]) == (0, {"no_barcode": 1}), report


def test_two_shops_describing_it_completely_meet_without_a_barcode(client):
    """The whole point of the second bar: the same complete description is the same key."""
    token = admin_token(client)
    shop, first, category, _ = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])
    a_colour_axis(client, token, category["id"])
    second = post(
        client,
        token,
        f"/api/admin/shops/{shop['id']}/sources",
        {
            "slug": "rd-other",
            "access": "wholesale",
            "decode": "xml",
            "delivers_full": ["catalogue", "price", "availability"],
            "trust": "high",
            "category_id": category["id"],
        },
    )
    body = {
        "brand": "Apple",
        "model": "iPhone 15",
        "attributes": {"storage": "256 GB", "color": "black"},
    }
    mine = offer_from(
        client,
        token,
        first["id"],
        {**body, "name": "Apple iPhone 15 256 GB black"},
        external_id="A-1",
    )
    theirs = offer_from(
        client,
        token,
        second["id"],
        {**body, "name": "iPhone 15, 256 GB, black"},
        external_id="B-1",
    )

    promote(client, token, mine)
    assert run_on(client, token, theirs)["matched"] is True
    assert client.get("/api/admin/variants", headers=auth(token)).json()["total"] == 1


def test_an_entry_that_knows_its_colour_beats_one_that_does_not(client):
    """An entry recording no colour agrees with every colour, having nothing to disagree
    with. One of those beside a real one made every coloured listing of that model
    ambiguous — and which won depended on the order they arrived in."""
    token = admin_token(client)
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    a_storage_axis(client, token, category["id"])
    a_colour_axis(client, token, category["id"])

    # One entry from a listing that never said a colour, and one that did.
    promote(
        client,
        token,
        offer_from(
            client,
            token,
            source["id"],
            {
                "name": "Apple iPhone 15 256 GB",
                "brand": "Apple",
                "model": "iPhone 15",
                "ean": "4006381333931",
                "attributes": {"storage": "256 GB"},
            },
            external_id="A-1",
        ),
    )
    promote(
        client,
        token,
        offer_from(
            client,
            token,
            source["id"],
            {
                "name": "Apple iPhone 15 256 GB black",
                "brand": "Apple",
                "model": "iPhone 15",
                "ean": "5902983617747",
                "attributes": {"storage": "256 GB", "color": "black"},
            },
            external_id="A-2",
        ),
    )

    # A third listing states black. Both entries agree with it; only one knows why.
    third = offer_from(
        client,
        token,
        source["id"],
        {
            "name": "iPhone 15 black",
            "brand": "Apple",
            "model": "iPhone 15",
            "attributes": {"storage": "256 GB", "color": "black"},
        },
        external_id="A-3",
    )
    outcome = run_on(client, token, third)
    assert outcome["matched"] is True, "the colourless entry no longer makes this a question"
    assert outcome["method"] == "brand_model"


def test_a_brand_the_shop_got_wrong_is_read_off_the_title(client):
    """bm.market files eight Google Pixels under `Getnord`, a maker of rugged phones that
    did not make them. The title, the model, the colour and the capacity all agree with the
    Pixels four other shops sell; only the one field disagrees.

    Entering `Getnord` in the registry would be worse than leaving it out: the listing would
    stop being visibly unplaced and start being confidently filed under the wrong maker.
    """
    token = admin_token(client)
    _, source = setup_source(client, token)
    brand, _, variant = catalogue(client, token)
    offer = offer_from(
        client,
        token,
        source["id"],
        {
            "name": f"{brand['canonical_name']} iPhone 15 Pro 256GB",
            "brand": "Getnord",
            "model": "iPhone 15 Pro",
        },
    )

    outcome = run_on(client, token, offer)
    assert outcome["matched"] is True
    assert outcome["variant_id"] == variant["id"]


def test_a_brand_the_shop_stated_correctly_is_never_second_guessed(client):
    """The title is read only where the field resolved to nothing."""
    token = admin_token(client)
    _, source = setup_source(client, token)
    catalogue(client, token)
    offer = offer_from(
        client, token, source["id"], {"name": "Nokla phone", "brand": "Nokla", "model": "X1"}
    )

    assert run_on(client, token, offer)["reason"] == "brand_unknown"
