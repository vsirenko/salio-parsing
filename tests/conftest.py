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

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Country, Currency, User

# A separate database so a test run never touches development data — and under
# pytest-xdist one per worker, `app_test_gw0`, `app_test_gw1`: two runs emptying one database
# between each other's statements is the deadlock `.claude/rules/workflow.md` warned about.
BASE_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql+asyncpg://app:app@localhost:55432/app_test"
)
WORKER = os.getenv("PYTEST_XDIST_WORKER", "")
TEST_DATABASE_URL = f"{BASE_DATABASE_URL}_{WORKER}" if WORKER else BASE_DATABASE_URL
TEST_DATABASE = TEST_DATABASE_URL.rsplit("/", 1)[1]


# One round trip that empties every table and restarts every id.
#
# Not `TRUNCATE … RESTART IDENTITY CASCADE`: that takes a lock on and rewrites every table,
# empty or not, and was 50 of the 56 ms a test spent in setup. A delete from an empty table
# costs next to nothing, and most tables are empty after most tests. Every table the schema
# has, read from the database rather than kept in a list here: the list this replaced had
# missed `category_aliases`, which the cascade had been emptying behind its back. Foreign
# keys are not checked while it runs — the database is being emptied, and it saves putting
# the tables in dependency order. The ids restart so a test can still name `run 1`.
_EMPTY_EVERYTHING = """
do $$ declare t record; begin
    set local session_replication_role = replica;
    for t in select tablename from pg_tables where schemaname = 'public' loop
        execute format('delete from %I', t.tablename);
    end loop;
    for t in select sequencename from pg_sequences where schemaname = 'public' loop
        execute format('alter sequence %I restart', t.sequencename);
    end loop;
end $$
"""

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

    The engine keeps a pool. Every request, every fixture and every helper runs on the one
    session event loop (see `client`), so a pooled connection never crosses loops — which
    is what used to force `NullPool`, and with it a new connection for the request, another
    for the audit middleware and another for the sign-in limiter on every call: 16 ms each
    against 0.3 ms for a query on an open one, measured on 24.09.2026.
    """
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    os.environ["DB_USE_NULL_POOL"] = "false"


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
    if name != TEST_DATABASE or "_test" not in name:
        raise RuntimeError(
            f"the tests are pointed at '{name}', which is not a test database. Something"
            " imported the application before pytest_configure ran — look for an import of"
            " app.core or app.features at the top of a conftest or a test module."
        )


async def _create_database_if_missing() -> None:
    """A worker's database is made the first time that worker runs, next to the base one."""
    if not WORKER:
        return
    admin = create_async_engine(BASE_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            exists = await conn.scalar(
                text("select 1 from pg_database where datname = :name"), {"name": TEST_DATABASE}
            )
            if not exists:
                await conn.execute(text(f'create database "{TEST_DATABASE}"'))
    finally:
        await admin.dispose()


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
def schema(event_loop):
    """Create the schema once for the whole run."""

    async def setup():
        await _create_database_if_missing()
        # Each statement its own transaction. Dropping and creating the whole schema in one
        # holds a lock on every table, index and partition at once, and twelve workers doing
        # it together ran the server out of its lock table (`max_locks_per_transaction`).
        engine = create_async_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as conn:
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


@pytest.fixture(scope="session", autouse=True)
def cheap_passwords():
    """Argon2 with the smallest parameters it takes, for the whole run.

    Still argon2, still a real hash and a real verification — only the cost that makes a
    guess expensive is gone, and a test run guesses nothing: 24 ms a verification became
    0.4, on a sign-in nearly every test makes. Imported inside for the reason
    `_seeded_hash` is.
    """
    from pwdlib import PasswordHash
    from pwdlib.hashers.argon2 import Argon2Hasher

    from app.core import security

    kept = security._password_hash
    security._password_hash = PasswordHash(
        (Argon2Hasher(time_cost=1, memory_cost=1024, parallelism=1),)
    )
    yield
    security._password_hash = kept


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
def clean_database(event_loop, schema, cheap_passwords):
    """Empty every table and re-seed, before each test."""

    async def reset():
        from app.db.session import session_factory

        _refuse_anything_but_the_test_database()
        async with session_factory() as session:
            await session.execute(text(_EMPTY_EVERYTHING))
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


class Client:
    """TestClient's synchronous face over an ASGI client on the session's event loop.

    Starlette's TestClient runs the app on a loop of its own per client, and a pooled
    asyncpg connection belongs to the loop that opened it; so the tests ran without a pool
    and paid a fresh connection three times a request. Here the app runs where the fixtures
    and helpers do, and the pool is shared by all of them. The app's lifespan does not run:
    it seeds the demo accounts, which `clean_database` has already done.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, app) -> None:
        self._loop = loop
        self._http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        )

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        return self._loop.run_until_complete(self._http.request(method, url, **kwargs))

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs) -> httpx.Response:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs) -> httpx.Response:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs) -> httpx.Response:
        return self.request("DELETE", url, **kwargs)

    def options(self, url: str, **kwargs) -> httpx.Response:
        return self.request("OPTIONS", url, **kwargs)

    def head(self, url: str, **kwargs) -> httpx.Response:
        return self.request("HEAD", url, **kwargs)

    def close(self) -> None:
        self._loop.run_until_complete(self._http.aclose())


@pytest.fixture
def client(event_loop):
    from app.main import app

    test_client = Client(event_loop, app)
    yield test_client
    test_client.close()


@pytest.fixture(scope="session")
def session_maker():
    engine = create_async_engine(TEST_DATABASE_URL)
    yield async_sessionmaker(engine, expire_on_commit=False)
