"""What shops write for a colour that did not become one — and why, in the rule's own terms."""

from tests.test_auth import auth
from tests.test_catalog import admin_token, post
from tests.test_matching import a_colour_axis, a_shop_we_can_build_from, offer_from


def a_colour_shop(client, token):
    _, source, category, _ = a_shop_we_can_build_from(client, token)
    colour = a_colour_axis(client, token, category["id"])
    for name in ("Krāsa", "Korpusa krāsa"):
        post(client, token, f"/api/admin/attributes/{colour['id']}/aliases", {"alias": name})
    return source, category, colour


def listing(client, token, source, external_id, attributes):
    return offer_from(
        client,
        token,
        source["id"],
        {"name": f"Apple iPhone 15 {external_id}", "brand": "Apple", "attributes": attributes},
        external_id=external_id,
    )


def report(client, token, **params):
    response = client.get(
        "/api/admin/offers/unresolved-colours", headers=auth(token), params=params
    )
    assert response.status_code == 200, response.text
    return response.json()


def by_value(body):
    return {value["value"]: value for value in body["values"]}


def test_each_value_says_why_it_did_not_become_a_colour(client):
    token = admin_token(client)
    source, _, _ = a_colour_shop(client, token)
    unknown = listing(client, token, source, "U-1", {"Krāsa": "Zilgans"})
    listing(client, token, source, "P-1", {"Krāsa": "Black, Blue"})
    listing(client, token, source, "C-1", {"Krāsa": "black", "Korpusa krāsa": "blue"})
    placed = listing(client, token, source, "OK-1", {"Krāsa": "black"})

    body = report(client, token)
    values = by_value(body)
    assert body["listings"] == 3
    assert body["by_reason"] == {"unknown": 1, "pair": 1, "conflict": 1}
    assert values["zilgans"]["reason"] == "unknown"
    assert values["zilgans"]["examples"][0]["offer_id"] == unknown
    assert values["zilgans"]["spellings"] == ["Zilgans"]
    # Both colours are known; the combination is not a value.
    assert (values["black, blue"]["reason"], values["black, blue"]["resolves_to"]) == (
        "pair",
        "black-blue",
    )
    # Each field resolves, to different colours: refused, and no alias would fix it.
    assert values["black"]["reason"] == "conflict"
    assert values["black"]["conflicts_with"] == ["blue"]
    assert values["blue"]["conflicts_with"] == ["black"]
    # A listing whose field did resolve is not on the list at all.
    assert all(
        example["offer_id"] != placed for value in body["values"] for example in value["examples"]
    )
    assert report(client, token, reason="pair")["values"][0]["value"] == "black, blue"


def test_a_word_entered_after_the_reading_resolves_now(client):
    """The registry moved and the reading did not: what a reparse is for."""
    token = admin_token(client)
    source, _, colour = a_colour_shop(client, token)
    listing(client, token, source, "L-1", {"Krāsa": "Melnais"})
    assert by_value(report(client, token))["melnais"]["reason"] == "unknown"

    black = next(
        value
        for value in client.get(
            f"/api/admin/attributes/{colour['id']}/values", headers=auth(token)
        ).json()
        if value["canonical"] == "black"
    )
    post(client, token, f"/api/admin/attributes/values/{black['id']}/aliases", {"alias": "melnais"})
    now = by_value(report(client, token))["melnais"]
    assert (now["reason"], now["resolves_to"]) == ("resolves_now", "black")


def test_a_word_marked_as_none_of_the_colours_leaves_the_list(client):
    token = admin_token(client)
    source, _, colour = a_colour_shop(client, token)
    listing(client, token, source, "P-1", {"Krāsa": "Melns, Zils"})
    url = f"/api/admin/attributes/{colour['id']}/dismissals"

    marked = post(client, token, url, {"value": " Melns, Zils ", "note": "two colours"})
    assert (marked["value"], marked["note"]) == ("melns, zils", "two colours")
    assert marked["dismissed_by"]
    assert report(client, token)["values"] == []
    [shown] = report(client, token, include_dismissed=True)["values"]
    assert shown["dismissed"] is True
    listed = client.get(url, headers=auth(token)).json()
    assert [item["value"] for item in listed] == ["melns, zils"]

    gone = client.delete(url, headers=auth(token), params={"value": "melns, zils"})
    assert gone.status_code == 204
    assert by_value(report(client, token))["melns, zils"]["dismissed"] is False
    again = client.delete(url, headers=auth(token), params={"value": "melns, zils"})
    assert again.status_code == 404
