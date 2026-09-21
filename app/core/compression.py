"""Accepting a compressed request body.

Starlette compresses responses and does not decompress requests, so a worker handing over
a few hundred listings would post megabytes of JSON uncompressed. Product JSON gzips by
roughly an order of magnitude, and the difference is paid on every pass of every channel.

Written as pure ASGI rather than a `BaseHTTPMiddleware`: the body has to be replaced before
anything downstream reads it, and the only place that is possible is the receive channel.
"""

import zlib

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# gzip rather than raw deflate.
_GZIP_WINDOW = 16 + zlib.MAX_WBITS


class TooLarge(Exception):
    """The body expanded past what was allowed. See `GzipRequestMiddleware`."""


class GzipRequestMiddleware:
    """Decompress `Content-Encoding: gzip` request bodies.

    The size cap is not tidiness. A few kilobytes of gzip can expand to gigabytes of zeros,
    so an uncapped decompressor turns any endpoint that accepts a body into a way to
    exhaust the machine's memory from outside. Expansion is checked as it happens rather
    than afterwards, because afterwards is too late.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _is_gzipped(scope):
            await self.app(scope, receive, send)
            return

        try:
            body = await self._read(receive)
        except (TooLarge, zlib.error) as error:
            await _refuse(send, error)
            return

        # The request no longer has the encoding or the length it announced. Left saying
        # otherwise, anything downstream that trusts `content-length` reads a body of a
        # different size than the one it was promised.
        await self.app({**scope, "headers": _rewrite(scope, len(body))}, _replay(body), send)

    async def _read(self, receive: Receive) -> bytes:
        decompressor = zlib.decompressobj(_GZIP_WINDOW)
        out = bytearray()
        more = True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                break
            out += decompressor.decompress(message.get("body", b""), self.max_bytes - len(out) + 1)
            if len(out) > self.max_bytes:
                raise TooLarge(f"body expands past {self.max_bytes} bytes")
            more = message.get("more_body", False)
        return bytes(out + decompressor.flush())


def _is_gzipped(scope: Scope) -> bool:
    for name, value in scope.get("headers", ()):
        if name == b"content-encoding" and b"gzip" in value.lower():
            return True
    return False


def _replay(body: bytes) -> Receive:
    """Hand the decompressed body to the app as if it had arrived that way."""
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


def _rewrite(scope: Scope, length: int) -> list[tuple[bytes, bytes]]:
    headers = [
        (name, value)
        for name, value in scope.get("headers", ())
        if name not in (b"content-encoding", b"content-length")
    ]
    headers.append((b"content-length", str(length).encode()))
    return headers


async def _refuse(send: Send, error: Exception) -> None:
    body = (
        b'{"error":{"code":"bad_request","message":"The compressed body could not be read: '
        + str(error).encode("utf-8", "replace").replace(b'"', b"'")
        + b'"}}'
    )
    await send(
        {
            "type": "http.response.start",
            "status": 400,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


__all__ = ["GzipRequestMiddleware", "TooLarge"]
