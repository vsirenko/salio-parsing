"""Test fixtures.

Tests run against a real PostgreSQL, not SQLite: the schema uses JSONB, arrays and a
functional unique index, so a different engine would test something we do not ship.

Isolation is by truncation rather than by rolling back a shared transaction, because
the audit middleware deliberately writes in its own transaction — a rollback-based
fixture would hide exactly the behaviour we want to verify.
"""

import asyncio
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Product

# A separate database so a test run never touches development data.
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql+asyncpg://app:app@localhost:55432/app_test"
)

TABLES = ("audit_entries", "login_attempts", "products", "users")

SEED_PRODUCTS = (
    ("Espresso machine", "499.99", ["kitchen", "coffee"]),
    ("Ceramic mug", "14.50", ["kitchen"]),
    ("Coffee beans 1kg", "24.00", ["coffee", "consumable"]),
)


def pytest_configure() -> None:
    """Point the app at the test database before anything imports the engine.

    NullPool because every TestClient runs its own event loop and an asyncpg
    connection cannot cross loops.
    """
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    os.environ["DB_USE_NULL_POOL"] = "true"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
def schema(event_loop):
    """Create the schema once for the whole run."""

    async def setup():
        engine = create_async_engine(TEST_DATABASE_URL)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
                await conn.run_sync(Base.metadata.create_all)
        finally:
            await engine.dispose()

    event_loop.run_until_complete(setup())


@pytest.fixture(autouse=True)
def clean_database(event_loop, schema):
    """Empty every table and re-seed, before each test."""

    async def reset():
        from app.db.session import session_factory
        from app.services.users import seed_users

        async with session_factory() as session:
            await session.execute(text(f"truncate {', '.join(TABLES)} restart identity cascade"))
            await session.commit()

        async with session_factory() as session:
            await seed_users(session)
            for name, price, tags in SEED_PRODUCTS:
                session.add(Product(name=name, price=price, currency="EUR", tags=tags))
            await session.commit()

    event_loop.run_until_complete(reset())


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def session_maker():
    engine = create_async_engine(TEST_DATABASE_URL)
    yield async_sessionmaker(engine, expire_on_commit=False)
