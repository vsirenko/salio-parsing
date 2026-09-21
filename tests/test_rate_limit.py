"""Sign-in rate limiting.

The limits come from settings; these tests read them rather than hard-coding numbers,
so tightening a limit does not turn into a test failure.
"""

from app.core.config import settings
from tests.test_auth import ADMIN, CUSTOMER, auth, tokens

WRONG = {**CUSTOMER, "password": "definitely-not-it"}
LIMIT = settings.login_max_failures_per_account


def fail_once(client, credentials=None) -> int:
    return client.post("/api/auth/login", json=credentials or WRONG).status_code


def test_repeated_failures_lock_the_account(client):
    for _ in range(LIMIT - 1):
        assert fail_once(client) == 401

    # The attempt that crosses the limit is still answered as a failed sign-in;
    # the lock applies from the next one.
    assert fail_once(client) == 401

    response = client.post("/api/auth/login", json=WRONG)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert int(response.headers["Retry-After"]) > 0


def test_the_lock_applies_to_the_right_password_too(client):
    """Otherwise the limit only slows down an attacker who never guesses right."""
    for _ in range(LIMIT):
        fail_once(client)

    assert client.post("/api/auth/login", json=CUSTOMER).status_code == 429


def test_a_successful_sign_in_clears_the_account(client):
    for _ in range(LIMIT - 1):
        assert fail_once(client) == 401
    assert client.post("/api/auth/login", json=CUSTOMER).status_code == 200

    # The budget is back: one more failure is nowhere near the limit again.
    assert fail_once(client) == 401
    assert client.post("/api/auth/login", json=CUSTOMER).status_code == 200


def test_the_lock_is_per_account(client):
    for _ in range(LIMIT):
        fail_once(client)

    assert client.post("/api/auth/login", json=WRONG).status_code == 429
    # A different account behind the same address still has its own budget, as long as
    # the looser per-address limit has not been reached.
    assert client.post("/api/admin/auth/login", json=ADMIN).status_code == 200


def test_unknown_emails_are_limited_too(client):
    """An account that does not exist must not be a free oracle."""
    ghost = {"email": "ghost@example.com", "password": "whatever"}
    for _ in range(LIMIT):
        assert fail_once(client, ghost) == 401

    assert client.post("/api/auth/login", json=ghost).status_code == 429


def test_the_admin_panel_is_limited_as_well(client):
    wrong_admin = {**ADMIN, "password": "nope"}
    for _ in range(LIMIT):
        assert client.post("/api/admin/auth/login", json=wrong_admin).status_code == 401

    assert client.post("/api/admin/auth/login", json=wrong_admin).status_code == 429


def test_a_lockout_is_recorded_in_the_audit_trail(client):
    # A made-up admin email, so the real admin account stays unlocked and can still
    # read the trail afterwards.
    ghost = {"email": "ghost-admin@example.com", "password": "nope"}
    for _ in range(LIMIT + 1):
        client.post("/api/admin/auth/login", json=ghost)

    token = tokens(client, ADMIN, panel="/admin")["access_token"]
    entries = client.get(
        "/api/admin/audit", headers=auth(token), params={"path": "/auth/login"}
    ).json()["items"]
    # Newest first, and the newest sign-in here is the successful one just above.
    locked_out = next(e for e in entries if e["status_code"] == 429)
    assert locked_out["actor_email"] == ghost["email"]
