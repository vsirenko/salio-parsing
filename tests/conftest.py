"""Test fixtures.

Tests run against a real PostgreSQL, not SQLite: the schema uses JSONB, arrays and a
functional unique index, so a different engine would test something we do not ship.

Isolation is by truncation rather than by rolling back a shared transaction, because
the audit middleware deliberately writes in its own transaction — a rollback-based
fixture would hide exactly the behaviour we want to verify.
"""

import asyncio
import os
from functools import cache

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Country, Currency, User

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
    "judge_verdicts",
    "runs",
    "match_queue",
    "offer_matches",
    "price_events",
    "availability_events",
    "normalized_offers",
    "raw_offers",
    "offers",
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
    "model_aliases",
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


def _refuse_anything_but_the_test_database() -> None:
    """Checked before every truncation, not once at startup.

    `pytest_configure` runs after this module is imported, so anything here that reaches
    `app.core` or `app.features` at import time builds the settings — and therefore the
    engine — from `.env`, pointing at the development database. The fixtures below then
    empty it, table by table, before every test.

    That is not hypothetical. It happened: an import added to the top of this file wiped a
    development database holding a real collected catalogue. A docstring saying "before
    anything imports the engine" was not enough, so this is a check instead.
    """
    from app.db.session import engine

    name = engine.url.database or ""
    if not name.endswith("_test"):
        raise RuntimeError(
            f"the tests are pointed at '{name}', which is not a test database. Something"
            " imported the application before pytest_configure ran — look for an import of"
            " app.core or app.features at the top of a conftest or a test module."
        )


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
                # `create_all` builds the partitioned parent and knows nothing about its
                # partitions, which only the migration creates — so without this every
                # insert into price_events fails with "no partition found for row". One
                # default partition is enough here; that the monthly ones are right is the
                # migration's business, not this fixture's.
                for parent in ("price_events", "availability_events"):
                    await conn.execute(
                        text(
                            f"create table if not exists {parent}_default"
                            f" partition of {parent} default"
                        )
                    )
        finally:
            await engine.dispose()

    event_loop.run_until_complete(setup())


@cache
def _seeded_hash(password: str) -> str:
    """Argon2 once per session instead of once per test.

    The same three demo passwords were hashed before every one of nearly four hundred
    tests, and argon2 is slow on purpose: 105 ms of the 150 ms it took to reset the
    database, which is forty seconds of a three-minute run spent computing the same three
    answers. The hashes are real ones — only the repetition is gone.

    Imported inside rather than at the top of the file for the same reason
    `pytest_configure` exists: anything reaching `app.core` or `app.features` early enough
    builds the engine before the test database has been named, and the connections it opens
    then belong to the wrong event loop.
    """
    from app.core.security import hash_password

    return hash_password(password)


@pytest.fixture(autouse=True)
def clean_database(event_loop, schema):
    """Empty every table and re-seed, before each test."""

    async def reset():
        from app.db.session import session_factory

        _refuse_anything_but_the_test_database()
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
            # The same accounts `seed_users` would create, with the hashing done once.
            from app.features.users.service import SEED_ACCOUNTS

            for email, password, full_name, role in SEED_ACCOUNTS:
                session.add(
                    User(
                        email=email,
                        full_name=full_name,
                        role=role.value,
                        password_hash=_seeded_hash(password),
                    )
                )
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
