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
from app.db.models import Country, Currency

# A separate database so a test run never touches development data.
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql+asyncpg://app:app@localhost:55432/app_test"
)

TABLES = (
    "audit_entries",
    "login_attempts",
    "users",
    "markets",
    "attribute_value_aliases",
    "attribute_values",
    "attribute_aliases",
    "category_attributes",
    "attributes",
    "sellers",
    "sources",
    "shop_markets",
    "shops",
    "shop_groups",
    "variant_components",
    "variant_merges",
    "variant_mpns",
    "variant_gtins",
    "variant_attributes",
    "variants",
    "product_merges",
    "products",
    "brand_aliases",
    "brands",
    "categories",
    "countries",
    "currencies",
)

# Reference data. Duplicated from the migration on purpose: a migration has to stay
# self-contained and keep working against the code of its own day, so it cannot import
# this, and this cannot import it.
SEED_CURRENCIES = (("EUR", "Euro", "\u20ac", 2),)
SEED_COUNTRIES = (
    ("EE", "Estonia", "EUR", True),
    ("LT", "Lithuania", "EUR", True),
    ("LV", "Latvia", "EUR", True),
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
        from app.features.users.service import seed_users

        async with session_factory() as session:
            await session.execute(text(f"truncate {', '.join(TABLES)} restart identity cascade"))
            await session.commit()

        async with session_factory() as session:
            for code, name, symbol, minor_units in SEED_CURRENCIES:
                session.add(Currency(code=code, name=name, symbol=symbol, minor_units=minor_units))
            # Flushed before the countries that point at them: the foreign key is a
            # plain column rather than a relationship, so the unit of work has nothing
            # to order these two by.
            await session.flush()
            for code, name, currency_code, is_eu in SEED_COUNTRIES:
                session.add(Country(code=code, name=name, currency_code=currency_code, is_eu=is_eu))
            await seed_users(session)
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
