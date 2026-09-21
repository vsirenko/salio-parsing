"""How a collector talks to the service.

Over HTTP with its own credentials, not through the database. Two reasons, and the second
is the one that matters: a worker may one day run somewhere else, and a parser is the one
thing here that runs hostile input through itself all day — holding a database handle, a
compromised one owns everything, while holding a worker token it can hand over offers and
say how a run went.
"""

import gzip
import json
import logging
from types import TracebackType

import httpx2

from app.core.config import settings
from app.features.runs.schemas import Job, RunResult

log = logging.getLogger(__name__)

# Below this, compressing costs more than it saves.
_COMPRESS_OVER = 1024


class CollectorError(Exception):
    """The service refused or could not be reached. The run failed; say why."""


class Collector:
    """A signed-in worker session.

    The token is fetched once and held for the process. A run outliving an access token is
    possible on a slow channel, so a 401 is retried once through a fresh sign-in rather
    than failing the pass.
    """

    def __init__(self, *, base_url: str | None = None, client: httpx2.AsyncClient | None = None):
        self.base_url = (base_url or settings.api_base_url).rstrip("/")
        self._client = client or httpx2.AsyncClient(timeout=60.0)
        self._owned = client is None
        self._token: str | None = None

    async def __aenter__(self) -> "Collector":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._owned:
            await self._client.aclose()

    # --- what it may do ---

    async def job(self, run_id: int) -> Job:
        return Job.model_validate(await self._request("GET", f"/api/worker/runs/{run_id}"))

    async def hand_over(self, source_id: int, batch: dict) -> dict:
        """Post a pass, gzipped when it is worth it."""
        return await self._request(
            "POST", f"/api/worker/sources/{source_id}/offers/batch", body=batch
        )

    async def finish(self, run_id: int, result: RunResult) -> dict:
        return await self._request(
            "POST",
            f"/api/worker/runs/{run_id}/finish",
            body=result.model_dump(mode="json"),
        )

    # --- the session ---

    async def _sign_in(self) -> str:
        try:
            response = await self._client.post(
                f"{self.base_url}/api/worker/auth/login",
                json={
                    "email": settings.worker_email,
                    "password": settings.worker_password.get_secret_value(),
                },
            )
        except httpx2.HTTPError as error:
            # A service that is not answering is the commonest failure there is, and it
            # was the one path that let a raw transport error out of this class.
            raise CollectorError(f"could not reach {self.base_url}: {error}") from error
        if response.status_code != 200:
            raise CollectorError(f"could not sign in: {response.status_code} {response.text[:200]}")
        return response.json()["access_token"]

    async def _request(self, method: str, path: str, *, body: dict | None = None) -> dict:
        for attempt in (1, 2):
            if self._token is None:
                self._token = await self._sign_in()

            headers = {"authorization": f"Bearer {self._token}"}
            content = None
            if body is not None:
                raw = json.dumps(body).encode()
                headers["content-type"] = "application/json"
                if len(raw) > _COMPRESS_OVER:
                    raw = gzip.compress(raw)
                    headers["content-encoding"] = "gzip"
                content = raw

            try:
                response = await self._client.request(
                    method, f"{self.base_url}{path}", headers=headers, content=content
                )
            except httpx2.HTTPError as error:
                raise CollectorError(f"{method} {path}: {error}") from error

            if response.status_code == 401 and attempt == 1:
                # The pass outlived its access token. One retry, then it is a real failure.
                self._token = None
                continue
            if response.status_code >= 400:
                raise CollectorError(
                    f"{method} {path}: {response.status_code} {response.text[:200]}"
                )
            return response.json()

        raise CollectorError(f"{method} {path}: could not authenticate")  # pragma: no cover
