"""Audit trail tests: completeness, redaction and scope."""

ADMIN = {"email": "admin@example.com", "password": "admin-password"}
CUSTOMER = {"email": "customer@example.com", "password": "customer-password"}


def admin_token(client) -> str:
    response = client.post("/api/admin/auth/login", json=ADMIN)
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def entries(client, token: str, **params) -> list[dict]:
    response = client.get("/api/admin/audit", headers=auth(token), params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


# --- completeness ---


def test_admin_login_is_recorded(client):
    token = admin_token(client)
    logged = entries(client, token, path="/auth/login")
    assert len(logged) == 1
    assert logged[0]["method"] == "POST"
    assert logged[0]["status_code"] == 200
    assert logged[0]["outcome"] == "success"
    assert logged[0]["actor_email"] == ADMIN["email"]


def test_failed_admin_login_is_recorded(client):
    client.post("/api/admin/auth/login", json={**ADMIN, "password": "wrong"})
    token = admin_token(client)

    failures = entries(client, token, outcome="failure")
    assert len(failures) == 1
    assert failures[0]["status_code"] == 401
    # The attempt is attributed to the email that was tried, with no actor id.
    assert failures[0]["actor_email"] == ADMIN["email"]
    assert failures[0]["actor_id"] is None


def test_create_user_records_actor_target_and_changes(client):
    token = admin_token(client)
    created = client.post(
        "/api/admin/users",
        headers=auth(token),
        json={"email": "new@example.com", "password": "password123", "role": "admin"},
    )
    assert created.status_code == 201

    entry = entries(client, token, method="POST", path="/users")[0]
    assert entry["actor_email"] == ADMIN["email"]
    assert entry["actor_id"] == 1
    assert entry["target_type"] == "user"
    assert entry["target_id"] == str(created.json()["id"])
    assert entry["changes"]["email"] == "new@example.com"
    assert entry["changes"]["role"] == "admin"


def test_reads_are_recorded_too(client):
    token = admin_token(client)
    client.get("/api/admin/users", headers=auth(token))
    assert entries(client, token, method="GET", path="/users")


def test_rejected_requests_are_recorded(client):
    client.get("/api/admin/users")  # no token at all
    token = admin_token(client)

    denied = [e for e in entries(client, token) if e["status_code"] == 401]
    assert any(e["path"] == "/api/admin/users" for e in denied)


# --- redaction ---


def test_password_never_reaches_the_audit_trail(client):
    token = admin_token(client)
    client.post(
        "/api/admin/users",
        headers=auth(token),
        json={"email": "secret@example.com", "password": "super-secret-value"},
    )
    body = client.get("/api/admin/audit", headers=auth(token)).text
    assert "super-secret-value" not in body
    assert "password" not in body


def test_redact_scrubs_nested_structures():
    from app.core.audit import redact

    clean = redact(
        {
            "email": "a@b.c",
            "password": "raw",
            "nested": {"refresh_token": "t", "keep": 1},
            "items": [{"api_key": "k"}, {"ok": 2}],
        }
    )
    assert clean["email"] == "a@b.c"
    assert clean["password"] == "[redacted]"
    assert clean["nested"] == {"refresh_token": "[redacted]", "keep": 1}
    assert clean["items"] == [{"api_key": "[redacted]"}, {"ok": 2}]


# --- scope and access ---


def test_client_traffic_is_not_audited(client):
    client.post("/api/auth/login", json=CUSTOMER)
    client.get("/api/auth/me")

    token = admin_token(client)
    paths = {e["path"] for e in entries(client, token)}
    assert all(p.startswith("/api/admin") for p in paths)


def test_audit_trail_requires_an_admin_token(client):
    assert client.get("/api/admin/audit").status_code == 401

    customer = client.post("/api/auth/login", json=CUSTOMER).json()["access_token"]
    assert client.get("/api/admin/audit", headers=auth(customer)).status_code == 401


def test_audit_trail_is_read_only(client):
    token = admin_token(client)
    for method in (client.post, client.put, client.patch, client.delete):
        assert method("/api/admin/audit", headers=auth(token)).status_code == 405


def test_request_id_header_matches_the_entry(client):
    token = admin_token(client)
    response = client.get("/api/admin/users", headers=auth(token))
    request_id = response.headers["X-Request-ID"]

    entry = entries(client, token, method="GET", path="/users")[0]
    assert entry["request_id"] == request_id


def test_newest_entries_come_first(client):
    token = admin_token(client)
    client.get("/api/admin/users", headers=auth(token))
    client.get("/api/admin/users/1", headers=auth(token))

    logged = entries(client, token)
    assert [e["id"] for e in logged] == sorted((e["id"] for e in logged), reverse=True)


def test_filter_by_actor(client):
    token = admin_token(client)
    assert entries(client, token, actor_id=1)
    assert entries(client, token, actor_id=999) == []


# --- isolation ---


def test_concurrent_requests_do_not_mix_actors(event_loop):
    """Two admins acting at once must not be attributed to each other.

    On the session's loop, as every request in the run is: the engine's pool is shared, and
    a connection opened on another loop cannot be used on this one.
    """
    event_loop.run_until_complete(_two_admins_at_once())


async def _two_admins_at_once():
    import asyncio

    import httpx

    from app.main import app

    SECOND = {"email": "second@example.com", "password": "second-password"}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        first = (await ac.post("/api/admin/auth/login", json=ADMIN)).json()["access_token"]
        created = await ac.post(
            "/api/admin/users", headers=auth(first), json={**SECOND, "role": "admin"}
        )
        assert created.status_code == 201
        second_id = created.json()["id"]
        second = (await ac.post("/api/admin/auth/login", json=SECOND)).json()["access_token"]

        # 20 interleaved requests from two different admins, six in flight at a time. Each
        # holds two connections while it finishes — its own and the audit entry's — and the
        # pool has fifteen, so twenty at once wait on each other (TODO.md).
        gate = asyncio.Semaphore(6)

        async def one(token: str):
            async with gate:
                return await ac.get("/api/admin/users/1", headers=auth(token))

        await asyncio.gather(*[one(token) for token in [first, second] * 10])

        page = await ac.get("/api/admin/audit", headers=auth(first), params={"limit": 200})
        logged = page.json()["items"]

    by_user = [e for e in logged if e["path"] == "/api/admin/users/1"]
    assert len(by_user) == 20

    emails = {1: ADMIN["email"], second_id: SECOND["email"]}
    for entry in by_user:
        assert entry["actor_id"] in emails, "every action must carry a real actor"
        assert entry["actor_email"] == emails[entry["actor_id"]]
    assert {e["actor_id"] for e in by_user} == {1, second_id}
