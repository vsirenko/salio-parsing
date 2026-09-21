"""One run, executed.

    python -m app.features.runs.worker --run-id 42

Spawned by the scheduler, one process per run, so that a parser that leaks memory or
wedges takes its own process down and nothing else. A worker always finishes its own run:
the scheduler closes one only when the process is gone and the row is still open.

No channel is implemented yet, so every run ends the same way — as a failure that names
the channel it could not collect. That is the honest state: the machinery around
collecting is built and the collecting is not.
"""

import argparse
import asyncio
import logging

from sqlalchemy import select

from app.db.models import Source
from app.db.session import session_factory
from app.features.runs.schemas import RunResult
from app.features.runs.service import RunService

log = logging.getLogger(__name__)

# Channel implementations register here, keyed by source slug. Adding a channel is adding
# an entry; nothing else about the scheduler or the run lifecycle changes.
CHANNELS: dict[str, object] = {}


async def collect(run_id: int) -> RunResult:
    """Do the run. Today: find out that there is nothing to do it with."""
    async with session_factory() as session:
        run = await RunService(session).get(run_id)
        slug = await session.scalar(select(Source.slug).where(Source.id == run.source_id))

    channel = CHANNELS.get(slug)
    if channel is None:
        return RunResult(
            items_seen=0,
            items_ingested=0,
            error=f"no channel implementation registered for '{slug}'",
        )
    raise NotImplementedError  # pragma: no cover - unreachable while CHANNELS is empty


async def main(run_id: int) -> int:
    result = await collect(run_id)
    async with session_factory() as session:
        await RunService(session).finish(run_id, result)
        await session.commit()

    if result.error:
        log.error("run %d failed: %s", run_id, result.error)
        return 1
    log.info("run %d collected %d item(s)", run_id, result.items_ingested)
    return 0


if __name__ == "__main__":  # pragma: no cover
    from app.core.logging import configure_logging

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", type=int, required=True)
    arguments = parser.parse_args()

    configure_logging()
    raise SystemExit(asyncio.run(main(arguments.run_id)))
