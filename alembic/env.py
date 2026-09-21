import asyncio
from functools import lru_cache
from logging.config import fileConfig

from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
from app.core.config import settings  # noqa: E402
from app.db import models  # noqa: E402,F401  (imported so the tables register)
from app.db.base import Base  # noqa: E402

target_metadata = Base.metadata

config.set_main_option("sqlalchemy.url", str(settings.database_url))

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def skip_partitions(object, name, type_, reflected, compare_to) -> bool:
    """Keep autogenerate away from the partitions of a partitioned table.

    A partition is a real table in the catalogue but it is not in the models, so
    autogenerate reads it as something to drop — and `alembic check` fails on a schema that
    is in fact correct. Postgres already knows which tables are partitions; asking it is
    exact, where a name pattern would only be a guess.
    """
    return not (type_ == "table" and reflected and name in _partition_names())


@lru_cache(maxsize=1)
def _partition_names() -> frozenset[str]:
    connection = context.get_bind()
    if connection is None:
        return frozenset()
    rows = connection.execute(text("select relname from pg_class where relispartition")).scalars()
    return frozenset(rows)


def do_run_migrations(connection: Connection) -> None:
    _partition_names.cache_clear()
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=skip_partitions,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
