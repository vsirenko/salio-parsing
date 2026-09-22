"""The canonical attribute registry and what a category makes of it."""

from tests.test_auth import ADMIN, CUSTOMER, auth, tokens


def admin_token(client) -> str:
    return tokens(client, ADMIN, panel="/admin")["access_token"]


def add_attribute(client, token, key, name, value_type="enum", **extra):
    response = client.post(
        "/api/admin/attributes",
        headers=auth(token),
        json={"key": key, "name": name, "value_type": value_type, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def add_category(client, token, slug="phones", name="Phones"):
    response = client.post(
        "/api/admin/categories", headers=auth(token), json={"slug": slug, "name": name}
    )
    assert response.status_code == 201, response.text
    return response.json()


# --- the registry ---


def test_create_an_enum_and_a_number(client):
    token = admin_token(client)
    color = add_attribute(client, token, "color", "Colour")
    capacity = add_attribute(
        client, token, "capacity", "Capacity", "number", unit_dimension="bytes", scale=0
    )
    assert color["unit_dimension"] is None
    assert capacity["scale"] == 0


def test_a_unit_only_means_something_for_a_number(client):
    token = admin_token(client)
    response = client.post(
        "/api/admin/attributes",
        headers=auth(token),
        json={"key": "color", "name": "Colour", "value_type": "enum", "unit_dimension": "mass"},
    )
    assert response.status_code == 422


def test_the_key_is_normalised_and_shaped(client):
    token = admin_token(client)
    assert add_attribute(client, token, " Color ", "Colour")["key"] == "color"
    bad = client.post(
        "/api/admin/attributes",
        headers=auth(token),
        json={"key": "screen size", "name": "X", "value_type": "text"},
    )
    assert bad.status_code == 422


def test_the_key_is_unique(client):
    token = admin_token(client)
    add_attribute(client, token, "color", "Colour")
    again = client.post(
        "/api/admin/attributes",
        headers=auth(token),
        json={"key": "color", "name": "Colour again", "value_type": "enum"},
    )
    assert again.status_code == 409


# --- aliases: what the sources call it ---


def test_aliases_normalise_case_and_punctuation(client):
    token = admin_token(client)
    color = add_attribute(client, token, "color", "Colour")

    for raw in ("Krāsa", " Цвет: ", "Colour®"):
        response = client.post(
            f"/api/admin/attributes/{color['id']}/aliases",
            headers=auth(token),
            json={"alias": raw, "origin": "human"},
        )
        assert response.status_code == 201, response.text

    stored = {
        a["alias_normalized"]
        for a in client.get(
            f"/api/admin/attributes/{color['id']}/aliases", headers=auth(token)
        ).json()
    }
    assert stored == {"krāsa", "цвет", "colour"}


def test_two_shops_spelling_one_name_differently_are_one_alias(client):
    """A comma separates a qualifier a shop tacked on, never two names.

    Met on real data: one shop writes `Operatīvā atmiņa (RAM)` and the other
    `Operatīvā atmiņa, (RAM)`; one writes `Ekrāna izmērs` and the other `Ekrāna izmērs, "`,
    the unit appended to the name of the thing. Each spelling as its own row leaves a
    lookup guessing which it will meet.
    """
    token = admin_token(client)
    ram = add_attribute(client, token, "ram_gb", "RAM", value_type="number")

    first = client.post(
        f"/api/admin/attributes/{ram['id']}/aliases",
        headers=auth(token),
        json={"alias": "Operatīvā atmiņa (RAM)", "language": "lv"},
    )
    assert first.status_code == 201
    assert first.json()["alias_normalized"] == "operatīvā atmiņa (ram)"

    # The other shop's spelling is the same alias, so the registry refuses a second row.
    second = client.post(
        f"/api/admin/attributes/{ram['id']}/aliases",
        headers=auth(token),
        json={"alias": "Operatīvā atmiņa, (RAM)", "language": "lv"},
    )
    assert second.status_code == 409


def test_a_unit_written_into_the_name_is_not_part_of_it(client):
    token = admin_token(client)
    screen = add_attribute(client, token, "screen_inch", "Screen", value_type="number")
    response = client.post(
        f"/api/admin/attributes/{screen['id']}/aliases",
        headers=auth(token),
        json={"alias": 'Ekrāna izmērs, "', "language": "lv"},
    )
    assert response.json()["alias_normalized"] == "ekrāna izmērs"


def test_a_bracket_is_part_of_the_name_and_survives(client):
    """`(RAM)` names the thing; `®` decorates it."""
    from app.features.attributes.schemas import _normalize

    assert _normalize("Operatīvā atmiņa (RAM)").endswith("(ram)")
    assert _normalize("Colour®") == "colour"


def test_the_same_alias_twice_is_refused(client):
    token = admin_token(client)
    color = add_attribute(client, token, "color", "Colour")
    body = {"alias": "Krāsa"}
    assert (
        client.post(
            f"/api/admin/attributes/{color['id']}/aliases", headers=auth(token), json=body
        ).status_code
        == 201
    )
    # Same string, different casing — one alias, not two.
    assert (
        client.post(
            f"/api/admin/attributes/{color['id']}/aliases",
            headers=auth(token),
            json={"alias": "krāsa"},
        ).status_code
        == 409
    )


def test_one_string_may_belong_to_two_attributes(client):
    """`Размер` is a real name for both shoe size and clothing size; the category
    settles which one an offer means."""
    token = admin_token(client)
    shoe = add_attribute(client, token, "shoe_size", "Shoe size")
    clothing = add_attribute(client, token, "clothing_size", "Clothing size")

    for attribute in (shoe, clothing):
        response = client.post(
            f"/api/admin/attributes/{attribute['id']}/aliases",
            headers=auth(token),
            json={"alias": "Размер"},
        )
        assert response.status_code == 201, response.text


# --- canonical values ---


def test_values_and_their_aliases(client):
    token = admin_token(client)
    color = add_attribute(client, token, "color", "Colour")
    black = client.post(
        f"/api/admin/attributes/{color['id']}/values",
        headers=auth(token),
        json={"canonical": "black", "position": 1},
    )
    assert black.status_code == 201, black.text

    for alias, language in (("melns", "lv"), ("juodas", "lt"), ("must", "et"), ("чёрный", "ru")):
        response = client.post(
            f"/api/admin/attributes/values/{black.json()['id']}/aliases",
            headers=auth(token),
            json={"alias": alias, "language": language},
        )
        assert response.status_code == 201, response.text


def test_only_an_enum_has_canonical_values(client):
    token = admin_token(client)
    capacity = add_attribute(
        client, token, "capacity", "Capacity", "number", unit_dimension="bytes", scale=0
    )
    response = client.post(
        f"/api/admin/attributes/{capacity['id']}/values",
        headers=auth(token),
        json={"canonical": "256"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "not_an_enum"


def test_one_spelling_cannot_mean_two_values(client):
    token = admin_token(client)
    color = add_attribute(client, token, "color", "Colour")
    values = {}
    for canonical in ("black", "graphite"):
        values[canonical] = client.post(
            f"/api/admin/attributes/{color['id']}/values",
            headers=auth(token),
            json={"canonical": canonical},
        ).json()

    first = client.post(
        f"/api/admin/attributes/values/{values['black']['id']}/aliases",
        headers=auth(token),
        json={"alias": "melns"},
    )
    assert first.status_code == 201
    clash = client.post(
        f"/api/admin/attributes/values/{values['graphite']['id']}/aliases",
        headers=auth(token),
        json={"alias": "melns"},
    )
    assert clash.status_code == 409


# --- what a category makes of them ---


def test_attach_with_identity_and_ordering(client):
    token = admin_token(client)
    phones = add_category(client, token)
    color = add_attribute(client, token, "color", "Colour")
    capacity = add_attribute(
        client, token, "capacity", "Capacity", "number", unit_dimension="bytes", scale=0
    )

    for attribute, position in ((capacity, 1), (color, 2)):
        response = client.post(
            f"/api/admin/categories/{phones['id']}/attributes",
            headers=auth(token),
            json={"attribute_id": attribute["id"], "identity_bearing": True, "position": position},
        )
        assert response.status_code == 201, response.text

    listed = client.get(
        f"/api/admin/attributes/by-category/{phones['id']}", headers=auth(token)
    ).json()
    assert [a["attribute_id"] for a in listed] == [capacity["id"], color["id"]]
    assert all(a["identity_bearing"] for a in listed)


def test_the_same_attribute_means_different_things_in_two_categories(client):
    """Weight is an axis for food and a specification for a washing machine."""
    token = admin_token(client)
    food = add_category(client, token, "food", "Food")
    machines = add_category(client, token, "washing-machines", "Washing machines")
    weight = add_attribute(
        client, token, "weight", "Weight", "number", unit_dimension="mass", scale=0
    )

    for category, bearing in ((food, True), (machines, False)):
        response = client.post(
            f"/api/admin/categories/{category['id']}/attributes",
            headers=auth(token),
            json={"attribute_id": weight["id"], "identity_bearing": bearing},
        )
        assert response.status_code == 201, response.text

    in_food = client.get(
        f"/api/admin/attributes/by-category/{food['id']}", headers=auth(token)
    ).json()
    in_machines = client.get(
        f"/api/admin/attributes/by-category/{machines['id']}", headers=auth(token)
    ).json()
    assert in_food[0]["identity_bearing"] is True
    assert in_machines[0]["identity_bearing"] is False


def test_free_text_cannot_carry_identity(client):
    """Two spellings of one value would split a variant in two."""
    token = admin_token(client)
    phones = add_category(client, token)
    note = add_attribute(client, token, "note", "Seller note", "text")

    response = client.post(
        f"/api/admin/categories/{phones['id']}/attributes",
        headers=auth(token),
        json={"attribute_id": note["id"], "identity_bearing": True},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "text_cannot_bear_identity"

    # Attaching it as a plain specification is fine.
    plain = client.post(
        f"/api/admin/categories/{phones['id']}/attributes",
        headers=auth(token),
        json={"attribute_id": note["id"]},
    )
    assert plain.status_code == 201
    # And it cannot be promoted afterwards either.
    promote = client.patch(
        f"/api/admin/categories/{phones['id']}/attributes/{note['id']}",
        headers=auth(token),
        json={"identity_bearing": True},
    )
    assert promote.status_code == 422


def test_label_and_unit_are_per_category(client):
    token = admin_token(client)
    phones = add_category(client, token)
    size = add_attribute(
        client, token, "screen_size", "Screen size", "number", unit_dimension="length", scale=1
    )
    client.post(
        f"/api/admin/categories/{phones['id']}/attributes",
        headers=auth(token),
        json={"attribute_id": size["id"]},
    )

    response = client.patch(
        f"/api/admin/categories/{phones['id']}/attributes/{size['id']}",
        headers=auth(token),
        json={"label_override": "Diagonal", "display_unit": "in"},
    )
    assert response.status_code == 200
    assert response.json()["label_override"] == "Diagonal"
    assert response.json()["display_unit"] == "in"


def test_attaching_twice_is_refused_and_detaching_works(client):
    token = admin_token(client)
    phones = add_category(client, token)
    color = add_attribute(client, token, "color", "Colour")
    body = {"attribute_id": color["id"]}

    assert (
        client.post(
            f"/api/admin/categories/{phones['id']}/attributes", headers=auth(token), json=body
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/api/admin/categories/{phones['id']}/attributes", headers=auth(token), json=body
        ).status_code
        == 409
    )

    dropped = client.delete(
        f"/api/admin/categories/{phones['id']}/attributes/{color['id']}", headers=auth(token)
    )
    assert dropped.status_code == 204
    assert (
        client.get(f"/api/admin/attributes/by-category/{phones['id']}", headers=auth(token)).json()
        == []
    )


def test_unknown_category_or_attribute(client):
    token = admin_token(client)
    phones = add_category(client, token)
    assert (
        client.post(
            f"/api/admin/categories/{phones['id']}/attributes",
            headers=auth(token),
            json={"attribute_id": 999},
        ).status_code
        == 404
    )
    missing = client.get("/api/admin/attributes/by-category/999", headers=auth(token))
    assert missing.status_code == 404


# --- guards and the trail ---


def test_attributes_require_an_admin_token(client):
    user_token = tokens(client, CUSTOMER)["access_token"]
    assert client.get("/api/admin/attributes", headers=auth(user_token)).status_code == 401
    assert client.get("/api/admin/attributes").status_code == 401


def test_attaching_is_recorded_against_the_category(client):
    token = admin_token(client)
    phones = add_category(client, token)
    color = add_attribute(client, token, "color", "Colour")
    client.post(
        f"/api/admin/categories/{phones['id']}/attributes",
        headers=auth(token),
        json={"attribute_id": color["id"], "identity_bearing": True},
    )

    entries = client.get(
        "/api/admin/audit", headers=auth(token), params={"path": "/attributes"}
    ).json()["items"]
    entry = next(e for e in entries if e["method"] == "POST" and e["status_code"] == 201)
    assert entry["target_type"] == "category"
    assert entry["target_id"] == str(phones["id"])
    assert entry["changes"]["attached_attribute"] == "color"
    assert entry["changes"]["identity_bearing"] is True


# --- what shops call a category ---


def test_a_category_is_named_in_the_languages_shops_use(client):
    """Two jobs: the word a shop puts at the front of a title, and the name it gives the
    section a listing came from."""
    from tests.test_offers import post

    token = admin_token(client)
    phones = post(client, token, "/api/admin/categories", {"slug": "phones", "name": "Phones"})
    for word in ("Telefons", "„Tālrunis“", "Mobilie telefoni"):
        response = client.post(
            f"/api/admin/categories/{phones['id']}/aliases",
            headers=auth(token),
            json={"alias": word, "language": "lv"},
        )
        assert response.status_code == 201, response.text

    stored = {
        a["alias_normalized"]
        for a in client.get(
            f"/api/admin/categories/{phones['id']}/aliases", headers=auth(token)
        ).json()
    }
    # The shop's quotation marks are punctuation around the name, not part of it.
    assert stored == {"telefons", "tālrunis", "mobilie telefoni"}


def test_the_same_name_twice_is_refused(client):
    from tests.test_offers import post

    token = admin_token(client)
    phones = post(client, token, "/api/admin/categories", {"slug": "phones", "name": "Phones"})
    body = {"alias": "Telefons", "language": "lv"}
    assert (
        client.post(
            f"/api/admin/categories/{phones['id']}/aliases", headers=auth(token), json=body
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/api/admin/categories/{phones['id']}/aliases",
            headers=auth(token),
            json={"alias": " telefons ", "language": "lv"},
        ).status_code
        == 409
    )
