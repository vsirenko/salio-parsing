"""Engine and session wiring.

Two ways in on purpose:

- `get_session` yields the request-scoped session, committed when the handler returns
  and rolled back if it raises;
- `session_factory` hands out an independent session, which the audit middleware needs:
  a record of a failed request must survive that request's rollback.
"""

from collections.abc import AsyncIterator

from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

_pool_options = (
    {"poolclass": NullPool}
    if settings.db_use_null_pool
    else {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_pre_ping": True,  # a connection killed by the database is replaced
    }
)

engine = create_async_engine(str(settings.database_url), echo=settings.db_echo, **_pool_options)

session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """One transaction per request: commit on success, roll back on failure."""
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_connection() -> None:
    """Raises if the database is unreachable. Used by the readiness probe."""
    from sqlalchemy import text

    async with engine.connect() as conn:
        await conn.execute(text("select 1"))
