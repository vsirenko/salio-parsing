"""Getting bytes from a shop, politely and without falling over.

Everything general lives here so that a channel is only the part that is specific to one
shop. A channel that opened its own connections would have its own retry policy, its own
idea of how fast to go, and its own way of being wrong about it.
"""

import asyncio
import logging
import random
from types import TracebackType

import httpx2

from app.core.config import settings
from app.features.runs.channel import Part

log = logging.getLogger(__name__)

# Retried: a shop that is briefly unhappy, and the ones that rate-limit by status.
RETRY_ON = frozenset({408, 425, 429, 500, 502, 503, 504})


class FetchError(Exception):
    """The shop did not serve this, after trying. One product's problem, not the run's."""


class Fetcher:
    """A polite HTTP session for one run.

    Politeness is not decoration. A crawler that hammers a shop gets blocked, and a
    blocked channel is a channel that produces nothing until somebody notices — which is
    slower than crawling slowly.
    """

    def __init__(
        self,
        *,
        user_agent: str | None = None,
        concurrency: int | None = None,
        delay: float | None = None,
        retries: int | None = None,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        self.delay = settings.fetch_delay_seconds if delay is None else delay
        self.retries = settings.fetch_retries if retries is None else retries
        self._gate = asyncio.Semaphore(concurrency or settings.fetch_concurrency)
        self._client = client or httpx2.AsyncClient(
            timeout=settings.fetch_timeout_seconds,
            follow_redirects=True,
            headers={"user-agent": user_agent or settings.fetch_user_agent},
        )
        self._owned = client is None
        self.requests = 0

    async def __aenter__(self) -> "Fetcher":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._owned:
            await self._client.aclose()

    async def get(self, url: str, *, role: str = "detail", **kwargs) -> Part:
        return await self.request("GET", url, role=role, **kwargs)

    async def post(self, url: str, *, role: str = "detail", **kwargs) -> Part:
        return await self.request("POST", url, role=role, **kwargs)

    async def request(self, method: str, url: str, *, role: str = "detail", **kwargs) -> Part:
        """One response, after however many attempts it took.

        A 4xx that is not a rate limit is returned rather than raised: a product page that
        is gone is a fact about the shop, and the channel is what decides what that means.
        """
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            async with self._gate:
                if self.delay:
                    # Jittered, because a fixed delay across a dozen workers is a pattern
                    # that looks exactly like what it is.
                    await asyncio.sleep(self.delay * random.uniform(0.5, 1.5))  # noqa: S311
                try:
                    self.requests += 1
                    response = await self._client.request(method, url, **kwargs)
                except httpx2.HTTPError as error:
                    last = error
                    response = None

            if response is not None and response.status_code not in RETRY_ON:
                return Part(
                    role=role,
                    url=str(response.url),
                    status=response.status_code,
                    body=response.text,
                )

            if attempt < self.retries:
                wait = _backoff(response, attempt)
                log.info("%s %s -> retrying in %.1fs", method, url, wait)
                await asyncio.sleep(wait)

        if response is not None:
            raise FetchError(f"{method} {url}: {response.status_code} after {self.retries} retries")
        raise FetchError(f"{method} {url}: {last}")


def _backoff(response: httpx2.Response | None, attempt: int) -> float:
    """Honour `Retry-After` when the shop says how long, otherwise double.

    A shop that names a delay has told us the answer; guessing a shorter one is how a
    temporary rate limit becomes a ban.
    """
    if response is not None:
        header = response.headers.get("retry-after")
        if header and header.isdigit():
            return min(float(header), 120.0)
    return min(2.0**attempt, 30.0) * random.uniform(0.8, 1.2)  # noqa: S311
