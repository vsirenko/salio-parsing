"""Where a request came from, and what an address may show of itself.

`client_ip` is shared by the audit trail and the sign-in rate limiter: both key off the
caller's address and must agree on how it is derived. `masked_url` is shared by the
proxies screen and the collectors' logs: an address carries its credentials, and neither
may print them.
"""

from urllib.parse import urlsplit

from starlette.requests import Request

MASK = "***"


def masked_url(url: str) -> str:
    """`http://user:pass@host:8080` -> `http://***@host:8080`: which address, not how in."""
    parts = urlsplit(url)
    if parts.username is None and parts.password is None:
        return url
    host = parts.hostname or ""
    try:
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        port = ""
    return f"{parts.scheme}://{MASK}@{host}{port}"


def client_ip(request: Request, *, trust_proxy_headers: bool) -> str | None:
    """The caller's address, or None when the transport does not report one.

    X-Forwarded-For is trivially spoofable unless a trusted proxy rewrites it, so it
    is only read when the deployment says there is one. Trusting it blindly would let
    a caller mint a fresh rate-limit bucket per request.
    """
    if trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None
