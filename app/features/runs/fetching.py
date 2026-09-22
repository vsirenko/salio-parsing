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


class Rate:
    """How many requests may be *started* per second, whatever is in flight.

    Separate from the concurrency limit because they answer different questions, and
    conflating them is how a polite crawler becomes a slow one by accident. The delay used
    to be slept inside the semaphore, which meant it held a slot: the real rate was
    `concurrency / (delay + latency)`, so raising the concurrency and lengthening the pause
    cancelled out and neither number said what it meant. Measured on a live shop, four slots
    and half a second gave 2.2 products a second where the same politeness spread over six
    slots gives more than twice that.

    Spaced rather than bursty, and jittered: a fixed interval across a dozen workers is a
    pattern that looks exactly like what it is.
    """

    def __init__(self, per_second: float) -> None:
        self.interval = 0.0 if per_second <= 0 else 1.0 / per_second
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def wait(self) -> None:
        if not self.interval:
            return
        # The lock is held only to book a departure time, never while sleeping — holding it
        # across the sleep would serialise every request onto one queue again.
        async with self._lock:
            now = asyncio.get_running_loop().time()
            start = max(now, self._next)
            self._next = start + self.interval * random.uniform(0.85, 1.15)  # noqa: S311
        pause = start - now
        if pause > 0:
            await asyncio.sleep(pause)


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
        rate: float | None = None,
        retries: int | None = None,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        self.retries = settings.fetch_retries if retries is None else retries
        # Two limits, and each says what it is. The gate is how many requests may be open
        # at once; the rate is how many may be started per second. A shop that answers in
        # fifty milliseconds would otherwise be asked a hundred times a second by six slots
        # that are all technically within their concurrency.
        self._gate = asyncio.Semaphore(concurrency or settings.fetch_concurrency)
        self._rate = Rate(settings.fetch_rate_per_second if rate is None else rate)
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
            # Outside the gate on purpose. Waiting for a departure slot while holding one of
            # the concurrency slots is what made the delay cost throughput rather than only
            # spacing requests out.
            await self._rate.wait()
            async with self._gate:
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
