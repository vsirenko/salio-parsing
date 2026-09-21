"""Shared pagination: the envelope, the caps, and offset vs cursor behaviour."""

from app.schemas.pagination import Page, Pagination

ADMIN = {"email": "admin@example.com", "password": "admin-password"}


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def admin_token(client) -> str:
    return client.post("/api/admin/auth/login", json=ADMIN).json()["access_token"]


# --- the envelope ---


def test_page_of_reports_more_pages():
    page = Page[int].of([1, 2], total=5, pagination=Pagination(limit=2, offset=0))
    assert page.has_more is True
    assert page.next_cursor is None
    assert (page.limit, page.offset, page.total) == (2, 0, 5)


def test_page_of_reports_last_page():
    page = Page[int].of([5], total=5, pagination=Pagination(limit=2, offset=4))
    assert page.has_more is False


def test_slice_applies_the_window():
    items = [10, 9, 8, 7]
    assert Pagination(limit=2).slice(items) == [10, 9]
    assert Pagination(limit=2, offset=2).slice(items) == [8, 7]
    assert Pagination(limit=2, offset=10).slice(items) == []


def test_next_cursor_only_in_cursor_mode():
    class Row:
        def __init__(self, id):
            self.id = id

    rows = [Row(9), Row(8)]
    assert Page[object].of(rows, total=5, pagination=Pagination(limit=2)).next_cursor is None
    cursor_page = Page[object].of(rows, total=5, pagination=Pagination(limit=2, cursor_mode=True))
    assert cursor_page.next_cursor == 8


# --- caps ---


def test_limit_cap_is_enforced(client):
    token = admin_token(client)
    listing = "/api/admin/countries"
    assert client.get(listing, params={"limit": 100}, headers=auth(token)).status_code == 200
    assert client.get(listing, params={"limit": 101}, headers=auth(token)).status_code == 422


def test_audit_has_its_own_wider_cap(client):
    token = admin_token(client)
    assert (
        client.get("/api/admin/audit", params={"limit": 200}, headers=auth(token)).status_code
        == 200
    )
    assert (
        client.get("/api/admin/audit", params={"limit": 201}, headers=auth(token)).status_code
        == 422
    )


def test_negative_offset_is_rejected(client):
    token = admin_token(client)
    response = client.get("/api/admin/countries", params={"offset": -1}, headers=auth(token))
    assert response.status_code == 422


# --- offset paging ---


def test_offset_paging_walks_the_collection(client):
    token = admin_token(client)
    listing = "/api/admin/countries"
    first = client.get(listing, params={"limit": 2, "offset": 0}, headers=auth(token)).json()
    second = client.get(listing, params={"limit": 2, "offset": 2}, headers=auth(token)).json()

    assert [i["code"] for i in first["items"]] == ["EE", "LT"]
    assert [i["code"] for i in second["items"]] == ["LV"]
    assert first["has_more"] is True
    assert second["has_more"] is False


def test_users_endpoint_uses_the_same_envelope(client):
    from app.features.users.service import SEED_ACCOUNTS

    token = admin_token(client)
    body = client.get("/api/admin/users", params={"limit": 1}, headers=auth(token)).json()
    assert set(body) == {"items", "total", "limit", "offset", "next_cursor", "has_more"}
    # Counted from the seed rather than written out: a new demo account is not a reason
    # for an envelope test to fail.
    assert body["total"] == len(SEED_ACCOUNTS)
    assert body["has_more"] is True


# --- cursor paging ---


def noise(client, token: str, count: int) -> None:
    """Each admin request appends one audit entry."""
    for _ in range(count):
        client.get("/api/admin/users", headers=auth(token))


def test_cursor_page_exposes_the_next_anchor(client):
    token = admin_token(client)
    noise(client, token, 10)

    page = client.get("/api/admin/audit", params={"limit": 5}, headers=auth(token)).json()
    assert len(page["items"]) == 5
    assert page["has_more"] is True
    assert page["next_cursor"] == page["items"][-1]["id"]


def test_cursor_paging_does_not_repeat_rows_when_the_trail_grows(client):
    """The reason the audit trail pages by cursor rather than offset."""
    token = admin_token(client)
    noise(client, token, 10)

    first = client.get("/api/admin/audit", params={"limit": 5}, headers=auth(token)).json()
    seen = [e["id"] for e in first["items"]]

    # New entries land at the top between the two requests.
    noise(client, token, 4)

    by_cursor = client.get(
        "/api/admin/audit",
        params={"limit": 5, "before_id": first["next_cursor"]},
        headers=auth(token),
    ).json()
    cursor_ids = [e["id"] for e in by_cursor["items"]]
    assert not set(cursor_ids) & set(seen), "cursor paging must not repeat rows"
    assert max(cursor_ids) < min(seen)

    # Offset paging over the same growing feed does repeat rows — this is the bug.
    by_offset = client.get(
        "/api/admin/audit", params={"limit": 5, "offset": 5}, headers=auth(token)
    ).json()
    assert set(e["id"] for e in by_offset["items"]) & set(seen)


def test_cursor_walks_to_the_end(client):
    token = admin_token(client)
    noise(client, token, 8)

    collected: list[int] = []
    cursor = None
    for _ in range(10):  # guard against an infinite loop
        params = {"limit": 3} | ({"before_id": cursor} if cursor else {})
        page = client.get("/api/admin/audit", params=params, headers=auth(token)).json()
        collected += [e["id"] for e in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert cursor is None, "paging should terminate"
    assert len(collected) == len(set(collected)), "no row seen twice"
    assert collected == sorted(collected, reverse=True)
