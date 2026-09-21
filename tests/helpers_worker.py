"""A stand-in worker for the scheduler tests.

Spawned as a subprocess and closes its own run, so the scheduler's rule — close a run only
when the process is gone and the row is still open — can be exercised without the real
worker, which reaches the service over HTTP and would aim at whatever is listening on the
configured port.
"""

from app.db.session import session_factory
from app.features.runs.schemas import RunResult
from app.features.runs.service import RunService


async def close(run_id: int) -> None:
    async with session_factory() as session:
        await RunService(session).finish(
            run_id,
            RunResult(items_seen=0, items_ingested=0, error="reported by the worker"),
        )
        await session.commit()
