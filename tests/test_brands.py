"""Brands, their aliases, and what a string resolves to."""

import pytest

from app.features.brands.normalization import normalize_brand
from tests.test_auth import ADMIN, CUSTOMER, auth, tokens


def admin_token(client) -> str:
    return tokens(client, ADMIN, panel="/admin")["access_token"]


def add_brand(client, token, slug, name):
    response = client.post(
        "/api/admin/brands", headers=auth(token), json={"slug": slug, "canonical_name": name}
    )
    assert response.status_code == 201, response.text
    return response.json()


def add_alias(client, token, brand_id, alias, kind="spelling"):
    return client.post(
        f"/api/admin/brands/{brand_id}/aliases",
        headers=auth(token),
        json={"alias": alias, "kind": kind},
    )


# --- normalization is a function, not rows ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Samsung", "samsung"),
        ("SAMSUNG", "samsung"),
        (" samsung ", "samsung"),
        ("Samsung®", "samsung"),
        ("Bosch GmbH", "bosch"),
        ("Ekspla UAB", "ekspla"),
        ("Rīgas Elektronika SIA", "rīgas elektronika"),
        ("Tallink OÜ", "tallink"),
        ("Elgiganten AB", "elgiganten"),
        ("Samsung Electronics Co., Ltd.", "samsung electronics"),
        # A legal form is only stripped at the end: AS starts plenty of real names.
        ("AS Tallinna", "as tallinna"),
        # ...and only as a word of its own. Samsungas is the Lithuanian declension of
        # Samsung; without a boundary check the Estonian AS eats its ending and it
        # becomes a different string. Saab would lose its tail to AB the same way.
        ("Samsungas", "samsungas"),
        ("Saab", "saab"),
        # A brand actually called AS keeps its name.
        ("AS", "as"),
    ],
)
def test_normalization(raw, expected):
    assert normalize_brand(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "®", "..."])
def test_nothing_left_is_refused(raw):
    """A blank alias would match every offer whose brand field is a stray mark."""
    with pytest.raises(ValueError):
        normalize_brand(raw)


# --- brands ---


def test_two_brands_may_share_a_name(client):
    """Delta is taps and machine tools: two companies, not a duplicate."""
    token = admin_token(client)
    add_brand(client, token, "delta", "Delta")
    second = client.post(
        "/api/admin/brands",
        headers=auth(token),
        json={"slug": "delta-tools", "canonical_name": "Delta"},
    )
    assert second.status_code == 201


def test_the_slug_is_what_is_unique(client):
    token = admin_token(client)
    add_brand(client, token, "delta", "Delta")
    clash = client.post(
        "/api/admin/brands",
        headers=auth(token),
        json={"slug": "delta", "canonical_name": "Something else"},
    )
    assert clash.status_code == 409


def test_search_by_name(client):
    token = admin_token(client)
    add_brand(client, token, "samsung", "Samsung")
    add_brand(client, token, "sony", "Sony")
    found = client.get("/api/admin/brands?search=sams", headers=auth(token)).json()
    assert [b["slug"] for b in found["items"]] == ["samsung"]


# --- aliases ---


def test_spellings_collapse_to_one_row(client):
    token = admin_token(client)
    brand = add_brand(client, token, "samsung", "Samsung")

    assert add_alias(client, token, brand["id"], "Samsung®").status_code == 201
    # Same string once the noise is computed away — one alias, not two.
    assert add_alias(client, token, brand["id"], "  samsung ").status_code == 409

    aliases = client.get(f"/api/admin/brands/{brand['id']}/aliases", headers=auth(token)).json()
    assert [a["alias_normalized"] for a in aliases] == ["samsung"]
    assert aliases[0]["alias_raw"] == "Samsung®"


def test_a_declension_is_its_own_row(client):
    """No rule derives Samsungo from Samsung; Lithuanian grammar is not a typo."""
    token = admin_token(client)
    brand = add_brand(client, token, "samsung", "Samsung")
    for alias in ("Samsung", "Samsungo", "Samsungas", "Самсунг"):
        assert add_alias(client, token, brand["id"], alias).status_code == 201


def test_an_alias_that_normalizes_to_nothing(client):
    token = admin_token(client)
    brand = add_brand(client, token, "samsung", "Samsung")
    assert add_alias(client, token, brand["id"], "®").status_code == 422


def test_remove_an_alias(client):
    token = admin_token(client)
    brand = add_brand(client, token, "samsung", "Samsung")
    alias = add_alias(client, token, brand["id"], "Samsungo").json()

    dropped = client.delete(
        f"/api/admin/brands/{brand['id']}/aliases/{alias['id']}", headers=auth(token)
    )
    assert dropped.status_code == 204
    assert client.get(f"/api/admin/brands/{brand['id']}/aliases", headers=auth(token)).json() == []


def test_an_alias_of_another_brand_is_not_removable_here(client):
    token = admin_token(client)
    samsung = add_brand(client, token, "samsung", "Samsung")
    sony = add_brand(client, token, "sony", "Sony")
    alias = add_alias(client, token, sony["id"], "Sony").json()

    response = client.delete(
        f"/api/admin/brands/{samsung['id']}/aliases/{alias['id']}", headers=auth(token)
    )
    assert response.status_code == 404


# --- resolution, which is what the matcher will call ---


def test_one_result_is_a_deterministic_signal(client):
    token = admin_token(client)
    brand = add_brand(client, token, "samsung", "Samsung")
    add_alias(client, token, brand["id"], "Самсунг")

    found = client.get("/api/admin/brands/resolve?q=САМСУНГ", headers=auth(token)).json()
    assert len(found) == 1
    assert found[0]["brand"]["slug"] == "samsung"
    assert found[0]["matched_alias"] == "самсунг"


def test_two_results_mean_the_category_has_to_settle_it(client):
    token = admin_token(client)
    taps = add_brand(client, token, "delta", "Delta")
    tools = add_brand(client, token, "delta-tools", "Delta")
    for brand in (taps, tools):
        add_alias(client, token, brand["id"], "Delta")

    found = client.get("/api/admin/brands/resolve?q=delta", headers=auth(token)).json()
    assert {m["brand"]["slug"] for m in found} == {"delta", "delta-tools"}


def test_nothing_known_resolves_to_nothing(client):
    token = admin_token(client)
    assert client.get("/api/admin/brands/resolve?q=Nokla", headers=auth(token)).json() == []


def test_a_line_is_not_read_from_a_title(client):
    """ "Spigen case for iPhone 15" is not an Apple product."""
    token = admin_token(client)
    apple = add_brand(client, token, "apple", "Apple")
    add_alias(client, token, apple["id"], "Apple", kind="spelling")
    add_alias(client, token, apple["id"], "iPhone", kind="line")

    # A feed's brand field saying iPhone does mean Apple.
    from_field = client.get("/api/admin/brands/resolve?q=iPhone", headers=auth(token)).json()
    assert [m["brand"]["slug"] for m in from_field] == ["apple"]

    # Read out of a title, it must not.
    from_title = client.get(
        "/api/admin/brands/resolve?q=iPhone&titles_only=true", headers=auth(token)
    ).json()
    assert from_title == []

    # The spelling still resolves either way.
    assert (
        client.get(
            "/api/admin/brands/resolve?q=Apple&titles_only=true", headers=auth(token)
        ).json()[0]["brand"]["slug"]
        == "apple"
    )


# --- guards and the trail ---


def test_brands_require_an_admin_token(client):
    user_token = tokens(client, CUSTOMER)["access_token"]
    assert client.get("/api/admin/brands", headers=auth(user_token)).status_code == 401
    assert client.get("/api/admin/brands").status_code == 401


def test_adding_an_alias_is_recorded(client):
    token = admin_token(client)
    brand = add_brand(client, token, "samsung", "Samsung")
    add_alias(client, token, brand["id"], "Самсунг")

    entries = client.get(
        "/api/admin/audit", headers=auth(token), params={"path": "/aliases"}
    ).json()["items"]
    entry = next(e for e in entries if e["status_code"] == 201)
    assert entry["target_type"] == "brand"
    assert entry["target_id"] == str(brand["id"])
    assert entry["changes"] == {"added_alias": "самсунг", "kind": "spelling"}
