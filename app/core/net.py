"""Where a request came from.

Shared by the audit trail and the sign-in rate limiter: both key off the caller's
address and must agree on how it is derived.
"""

from starlette.requests import Request


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
