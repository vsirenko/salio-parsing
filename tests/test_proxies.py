"""Proxies: named ways out, chosen by channels, their credentials never shown."""

import json

import httpx2
import pytest

from tests.test_auth import auth
from tests.test_matching import admin_token
from tests.test_runs import channel, start
from tests.test_worker import worker_token

URLS = ["http://alice:s3cret@10.0.0.1:8080", "socks5://bob:hunter2@10.0.0.2:1080"]


def add(client, token, expect=201, **body):
    response = client.post(
        "/api/admin/proxies", headers=auth(token), json={"name": "rd", "urls": URLS, **body}
    )
    assert response.status_code == expect, response.text
    return response.json()


def test_a_proxy_shows_its_addresses_without_their_credentials(client):
    token = admin_token(client)
    made = add(client, token)
    assert made["urls"] == ["http://***@10.0.0.1:8080", "socks5://***@10.0.0.2:1080"]
    body = client.get("/api/admin/proxies", headers=auth(token)).text
    assert "s3cret" not in body and "hunter2" not in body and "alice" not in body
    [entry] = client.get(
        "/api/admin/audit", headers=auth(token), params={"target_type": "proxy"}
    ).json()["items"]
    assert "s3cret" not in json.dumps(entry)
    assert entry["changes"]["urls"] == made["urls"]
    add(client, token, expect=409)


@pytest.mark.parametrize(
    "url",
    ["ftp://h:21", "http://host", "http://host:port", "http://u:p@host:80/path", "host:8080"],
)
def test_an_address_is_a_scheme_a_host_and_a_port(client, url):
    token = admin_token(client)
    refused = add(client, token, expect=422, urls=[url])
    assert "p@" not in json.dumps(refused)


def test_a_proxy_a_channel_uses_is_not_removed(client):
    token = admin_token(client)
    proxy = add(client, token)
    source = channel(client, token, cron_full=None, cron_quick=None)
    chosen = client.patch(
        f"/api/admin/sources/{source['id']}", headers=auth(token), json={"proxy_id": proxy["id"]}
    )
    assert (chosen.status_code, chosen.json()["proxy_id"]) == (200, proxy["id"])
    listed = client.get(f"/api/admin/proxies/{proxy['id']}", headers=auth(token)).json()
    assert listed["sources"] == [source["slug"]]

    refused = client.delete(f"/api/admin/proxies/{proxy['id']}", headers=auth(token))
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "proxy_in_use")
    client.patch(f"/api/admin/sources/{source['id']}", headers=auth(token), json={"proxy_id": None})
    gone = client.delete(f"/api/admin/proxies/{proxy['id']}", headers=auth(token))
    assert gone.status_code == 204
    unknown = client.patch(
        f"/api/admin/sources/{source['id']}", headers=auth(token), json={"proxy_id": 999999}
    )
    assert (unknown.status_code, unknown.json()["error"]["code"]) == (422, "unknown_proxy")


def test_the_worker_s_job_carries_the_addresses_whole_while_the_proxy_is_on(client):
    token = admin_token(client)
    proxy = add(client, token)
    source = channel(client, token, cron_full=None, cron_quick=None)
    client.patch(
        f"/api/admin/sources/{source['id']}", headers=auth(token), json={"proxy_id": proxy["id"]}
    )
    run = start(client, token, source["id"])
    worker = worker_token(client)

    def job():
        response = client.get(f"/api/worker/runs/{run['id']}", headers=auth(worker))
        assert response.status_code == 200, response.text
        return response.json()

    assert job()["proxies"] == URLS
    client.patch(
        f"/api/admin/proxies/{proxy['id']}", headers=auth(token), json={"is_enabled": False}
    )
    # Switched off, the channel goes direct.
    assert job()["proxies"] == []


def test_a_check_tries_every_address(client, monkeypatch):
    from app.features.proxies import service
    from app.features.proxies.schemas import AddressCheck, mask

    async def fake(url, probe):
        return AddressCheck(url=mask(url), ok="10.0.0.1" in url, ip="203.0.113.7", ms=12)

    monkeypatch.setattr(service, "check_address", fake)
    token = admin_token(client)
    proxy = add(client, token)
    checked = client.post(f"/api/admin/proxies/{proxy['id']}/check", headers=auth(token)).json()
    assert [a["ok"] for a in checked["addresses"]] == [True, False]
    assert "s3cret" not in json.dumps(checked)


# --- the fetcher, taking the addresses in turn ---


def fetcher(event_loop, *handlers):
    from app.features.runs.fetching import Fetcher

    clients = [httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) for handler in handlers]
    return Fetcher(rate=0, retries=2, clients=clients)


def test_an_address_that_fails_to_connect_is_out_and_the_next_one_answers(event_loop):
    seen: list[str] = []

    def down(request):
        seen.append("down")
        raise httpx2.ConnectError("refused", request=request)

    def up(request):
        seen.append("up")
        return httpx2.Response(200, text="ok")

    fetching = fetcher(event_loop, down, up)
    first = event_loop.run_until_complete(fetching.get("https://shop.example/a"))
    second = event_loop.run_until_complete(fetching.get("https://shop.example/b"))
    assert (first.status, second.status) == (200, 200)
    # Tried once, then left out: the second request never went near it.
    assert seen == ["down", "up", "up"]


def test_a_proxy_refusing_its_own_credentials_is_out_too(event_loop):
    def refusing(request):
        return httpx2.Response(407)

    def up(request):
        return httpx2.Response(200, text="ok")

    fetching = fetcher(event_loop, refusing, up)
    assert event_loop.run_until_complete(fetching.get("https://shop.example/a")).status == 200


def test_every_address_out_fails_the_request(event_loop):
    from app.features.runs.fetching import FetchError

    def down(request):
        raise httpx2.ProxyError("no route", request=request)

    fetching = fetcher(event_loop, down, down)
    with pytest.raises(FetchError, match="every proxy address is out"):
        event_loop.run_until_complete(fetching.get("https://shop.example/a"))
