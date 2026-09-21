"""Shops, the channels we read them through, and the sellers behind them."""

from tests.test_auth import ADMIN, CUSTOMER, auth, tokens


def admin_token(client) -> str:
    return tokens(client, ADMIN, panel="/admin")["access_token"]


def post(client, token, path, body, expect=201):
    response = client.post(path, headers=auth(token), json=body)
    assert response.status_code == expect, response.text
    return response.json()


def add_shop(client, token, slug="rd", name="RD Electronics", **extra):
    return post(
        client,
        token,
        "/api/admin/shops",
        {"slug": slug, "name": name, "country_code": "LV", **extra},
    )


def open_market(client, token, code="LV", slug="latvija"):
    return post(
        client,
        token,
        "/api/admin/markets",
        {"code": code, "name": code, "slug": slug, "languages": ["lv"]},
    )


# --- shops ---


def test_a_shop_is_based_in_a_country_not_a_market(client):
    """A German shop delivering to Riga is describable without a German storefront."""
    token = admin_token(client)
    post(
        client,
        token,
        "/api/admin/countries",
        {"code": "DE", "name": "Germany", "currency_code": "EUR", "is_eu": True},
    )
    shop = add_shop(client, token, slug="mediamarkt", name="MediaMarkt", country_code="DE")
    assert shop["country_code"] == "DE"


def test_an_unknown_country_is_refused_by_name(client):
    token = admin_token(client)
    response = client.post(
        "/api/admin/shops",
        headers=auth(token),
        json={"slug": "x", "name": "X", "country_code": "ZZ"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_country"


def test_the_slug_is_unique(client):
    token = admin_token(client)
    add_shop(client, token)
    response = client.post(
        "/api/admin/shops",
        headers=auth(token),
        json={"slug": "rd", "name": "Another", "country_code": "LV"},
    )
    assert response.status_code == 409


def test_an_ordinary_shop_gets_its_seller_with_it(client):
    """Price history is keyed by seller: an offer cannot attach to anything without one."""
    token = admin_token(client)
    shop = add_shop(client, token)

    sellers = client.get(f"/api/admin/shops/{shop['id']}/sellers", headers=auth(token)).json()
    assert len(sellers) == 1
    assert sellers[0]["external_id"] == "rd"
    assert sellers[0]["name"] == "RD Electronics"


def test_a_marketplace_starts_with_none(client):
    token = admin_token(client)
    shop = add_shop(client, token, slug="ozon", name="Ozon", is_marketplace=True)
    assert client.get(f"/api/admin/shops/{shop['id']}/sellers", headers=auth(token)).json() == []

    trader = post(
        client,
        token,
        f"/api/admin/shops/{shop['id']}/sellers",
        {"external_id": "trader-42", "name": "Some Trader"},
    )
    assert trader["shop_id"] == shop["id"]


def test_a_shop_that_is_not_a_marketplace_refuses_traders(client):
    """Several sellers in a shop that has one would put several price lines where one is."""
    token = admin_token(client)
    shop = add_shop(client, token)
    response = client.post(
        f"/api/admin/shops/{shop['id']}/sellers",
        headers=auth(token),
        json={"external_id": "trader-1", "name": "Trader"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "not_a_marketplace"


def test_is_marketplace_cannot_be_flipped(client):
    token = admin_token(client)
    shop = add_shop(client, token)
    response = client.patch(
        f"/api/admin/shops/{shop['id']}", headers=auth(token), json={"is_marketplace": True}
    )
    assert response.status_code == 422


# --- where its offers are shown ---


def test_a_shop_is_attached_to_a_market_disabled(client):
    token = admin_token(client)
    open_market(client, token)
    shop = add_shop(client, token)

    attached = client.put(f"/api/admin/shops/{shop['id']}/markets/LV", headers=auth(token), json={})
    assert attached.status_code == 200
    assert attached.json()["is_enabled"] is False

    enabled = client.put(
        f"/api/admin/shops/{shop['id']}/markets/lv",
        headers=auth(token),
        json={"is_enabled": True},
    )
    assert enabled.json()["is_enabled"] is True


def test_a_shop_can_be_switched_off_in_one_market_only(client):
    token = admin_token(client)
    open_market(client, token, "LV", "latvija")
    post(
        client,
        token,
        "/api/admin/markets",
        {"code": "LT", "name": "Lithuania", "slug": "lietuva", "languages": ["lt"]},
    )
    shop = add_shop(client, token)
    for code in ("LV", "LT"):
        client.put(
            f"/api/admin/shops/{shop['id']}/markets/{code}",
            headers=auth(token),
            json={"is_enabled": True},
        )

    client.put(
        f"/api/admin/shops/{shop['id']}/markets/LT",
        headers=auth(token),
        json={"is_enabled": False},
    )
    shown = client.get("/api/admin/shops?market_code=LV", headers=auth(token)).json()
    hidden = client.get("/api/admin/shops?market_code=LT", headers=auth(token)).json()
    assert shown["total"] == 1
    assert hidden["total"] == 0


def test_an_unopened_market_is_refused(client):
    token = admin_token(client)
    shop = add_shop(client, token)
    response = client.put(f"/api/admin/shops/{shop['id']}/markets/LV", headers=auth(token), json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_market"


def test_detach_a_market(client):
    token = admin_token(client)
    open_market(client, token)
    shop = add_shop(client, token)
    client.put(f"/api/admin/shops/{shop['id']}/markets/LV", headers=auth(token), json={})

    dropped = client.delete(f"/api/admin/shops/{shop['id']}/markets/LV", headers=auth(token))
    assert dropped.status_code == 204
    assert client.get(f"/api/admin/shops/{shop['id']}/markets", headers=auth(token)).json() == []


# --- how we read it ---


def test_a_shop_may_have_several_sources(client):
    """A feed and a scraper of one shop stay one shop. Hanging the seller off the source
    instead would make them two, with two price lines and two cards."""
    token = admin_token(client)
    shop = add_shop(client, token)
    post(
        client,
        token,
        f"/api/admin/shops/{shop['id']}/sources",
        {
            "slug": "rd-feed",
            "access": "wholesale",
            "decode": "xml",
            "delivers_full": ["catalogue", "price", "availability"],
            "trust": "high",
        },
    )
    post(
        client,
        token,
        f"/api/admin/shops/{shop['id']}/sources",
        {
            "slug": "rd-site",
            "access": "retail",
            "decode": "markup",
            "delivers_full": ["catalogue", "price", "availability"],
            "delivers_quick": ["price"],
            "trust": "low",
        },
    )

    sources = client.get(f"/api/admin/shops/{shop['id']}/sources", headers=auth(token)).json()
    assert {s["slug"] for s in sources} == {"rd-feed", "rd-site"}
    assert {s["trust"] for s in sources} == {"high", "low"}
    # And still one seller, because the shop is one shop.
    sellers = client.get(f"/api/admin/shops/{shop['id']}/sellers", headers=auth(token)).json()
    assert len(sellers) == 1


def test_a_source_starts_disabled_and_is_switched_on_separately(client):
    token = admin_token(client)
    shop = add_shop(client, token)
    source = post(
        client,
        token,
        f"/api/admin/shops/{shop['id']}/sources",
        {
            "slug": "rd-feed",
            "access": "wholesale",
            "decode": "xml",
            "delivers_full": ["catalogue", "price", "availability"],
        },
    )
    assert source["is_enabled"] is False
    assert source["trust"] == "medium"

    updated = client.patch(
        f"/api/admin/sources/{source['id']}",
        headers=auth(token),
        json={"is_enabled": True, "trust": "high"},
    ).json()
    assert updated["is_enabled"] is True
    assert updated["trust"] == "high"


def test_a_quick_pass_cannot_reach_past_the_full_one(client):
    """A cheap request cannot bring back more than an expensive one."""
    token = admin_token(client)
    shop = add_shop(client, token)
    response = client.post(
        f"/api/admin/shops/{shop['id']}/sources",
        headers=auth(token),
        json={
            "slug": "rd-site",
            "access": "retail",
            "decode": "markup",
            "delivers_full": ["catalogue", "price"],
            "delivers_quick": ["price", "availability"],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "quick_exceeds_full"


def test_a_wholesale_channel_has_no_quick_pass(client):
    """One request already returns everything, so there is nothing cheaper to run."""
    token = admin_token(client)
    shop = add_shop(client, token)
    response = client.post(
        f"/api/admin/shops/{shop['id']}/sources",
        headers=auth(token),
        json={
            "slug": "rd-feed",
            "access": "wholesale",
            "decode": "xml",
            "delivers_full": ["catalogue", "price", "availability"],
            "delivers_quick": ["price"],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "wholesale_has_no_quick_pass"


def test_narrowing_the_full_pass_is_checked_against_the_row(client):
    """The update sends one field; the rule spans two, and the other one is already stored."""
    token = admin_token(client)
    shop = add_shop(client, token)
    source = post(
        client,
        token,
        f"/api/admin/shops/{shop['id']}/sources",
        {
            "slug": "rd-site",
            "access": "retail",
            "decode": "markup",
            "delivers_full": ["catalogue", "price", "availability"],
            "delivers_quick": ["price", "availability"],
        },
    )
    response = client.patch(
        f"/api/admin/sources/{source['id']}",
        headers=auth(token),
        json={"delivers_full": ["catalogue", "price"]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "quick_exceeds_full"


def test_two_channels_into_one_shop_can_reach_different_things(client):
    """The reason a channel is the unit: same shop, same products, different coverage."""
    token = admin_token(client)
    shop = add_shop(client, token)
    for slug, decode, quick in (("rd-index", "private_api", []), ("rd-site", "markup", ["price"])):
        post(
            client,
            token,
            f"/api/admin/shops/{shop['id']}/sources",
            {
                "slug": slug,
                "access": "retail",
                "decode": decode,
                "delivers_full": ["catalogue", "price", "availability"],
                "delivers_quick": quick,
            },
        )

    sources = client.get(f"/api/admin/shops/{shop['id']}/sources", headers=auth(token)).json()
    by_slug = {s["slug"]: s for s in sources}
    assert by_slug["rd-index"]["delivers_quick"] == []
    assert by_slug["rd-site"]["delivers_quick"] == ["price"]
    # Fresh availability costs a full crawl on both, and that is a budget fact, not a bug.
    assert all("availability" not in s["delivers_quick"] for s in sources)


def test_trust_and_rating_are_different_things(client):
    """One is how much we believe the channel, the other what buyers think of the shop."""
    token = admin_token(client)
    shop = add_shop(client, token, rating="4.5")
    source = post(
        client,
        token,
        f"/api/admin/shops/{shop['id']}/sources",
        {
            "slug": "rd-site",
            "access": "retail",
            "decode": "markup",
            "delivers_full": ["catalogue", "price", "availability"],
            "delivers_quick": ["price"],
            "trust": "low",
        },
    )
    assert shop["rating"] == "4.50"
    assert source["trust"] == "low"


def test_a_rating_outside_the_scale(client):
    token = admin_token(client)
    response = client.post(
        "/api/admin/shops",
        headers=auth(token),
        json={"slug": "x", "name": "X", "country_code": "LV", "rating": "9"},
    )
    assert response.status_code == 422


# --- groups ---


def test_one_brand_over_two_countries(client):
    token = admin_token(client)
    post(
        client,
        token,
        "/api/admin/countries",
        {"code": "DE", "name": "Germany", "currency_code": "EUR", "is_eu": True},
    )
    group = post(
        client, token, "/api/admin/shop-groups", {"slug": "mediamarkt", "name": "MediaMarkt"}
    )
    lv = add_shop(client, token, slug="mm-lv", name="MediaMarkt LV", shop_group_id=group["id"])
    de = add_shop(
        client,
        token,
        slug="mm-de",
        name="MediaMarkt DE",
        country_code="DE",
        shop_group_id=group["id"],
    )
    assert lv["shop_group_id"] == de["shop_group_id"] == group["id"]
    assert lv["country_code"] != de["country_code"]


# --- guards and the trail ---


def test_shops_require_an_admin_token(client):
    user_token = tokens(client, CUSTOMER)["access_token"]
    assert client.get("/api/admin/shops", headers=auth(user_token)).status_code == 401
    assert client.get("/api/admin/shops").status_code == 401


def test_enabling_a_shop_in_a_market_is_recorded(client):
    token = admin_token(client)
    open_market(client, token)
    shop = add_shop(client, token)
    client.put(
        f"/api/admin/shops/{shop['id']}/markets/LV",
        headers=auth(token),
        json={"is_enabled": True},
    )

    entries = client.get(
        "/api/admin/audit", headers=auth(token), params={"path": "/markets/"}
    ).json()["items"]
    entry = next(e for e in entries if e["method"] == "PUT")
    assert entry["target_type"] == "shop"
    assert entry["target_id"] == str(shop["id"])
    assert entry["changes"] == {"market_code": "LV", "is_enabled": True}
