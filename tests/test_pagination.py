"""Shared pagination: the envelope, the caps, and offset vs cursor behaviour."""

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_product_service, get_user_service
from app.main import app
from app.schemas.pagination import Page, Pagination
from app.services.audit import AuditService
from app.services.products import ProductService
from app.services.users import UserService

ADMIN = {"email": "admin@example.com", "password": "admin-password"}


@pytest.fixture
def client():
    app.dependency_overrides[get_product_service] = lambda: ProductService()
    app.dependency_overrides[get_user_service] = lambda: UserService()
    app.state.audit_service = AuditService()
    yield TestClient(app)
    app.dependency_overrides.clear()


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
    assert client.get("/api/products", params={"limit": 100}).status_code == 200
    assert client.get("/api/products", params={"limit": 101}).status_code == 422


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
    assert client.get("/api/products", params={"offset": -1}).status_code == 422


# --- offset paging ---


def test_offset_paging_walks_the_collection(client):
    first = client.get("/api/products", params={"limit": 2, "offset": 0}).json()
    second = client.get("/api/products", params={"limit": 2, "offset": 2}).json()

    assert [i["id"] for i in first["items"]] == [1, 2]
    assert [i["id"] for i in second["items"]] == [3]
    assert first["has_more"] is True
    assert second["has_more"] is False


def test_users_endpoint_uses_the_same_envelope(client):
    token = admin_token(client)
    body = client.get("/api/admin/users", params={"limit": 1}, headers=auth(token)).json()
    assert set(body) == {"items", "total", "limit", "offset", "next_cursor", "has_more"}
    assert body["total"] == 2
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
