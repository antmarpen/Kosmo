"""Alembic migration environment (async engine over application settings).

The database URL always comes from `app.core.config` so the API, the worker,
and migrations share one configuration source.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

# Import models explicitly so fresh API, worker, and migration processes register
# every table referenced by SQLAlchemy foreign keys.
from app.domain.identity import models as _identity_models  # noqa: F401,E402
from app.domain.agents import models as _agent_models  # noqa: F401,E402
from app.domain.mcp_servers import models as _mcp_models  # noqa: F401,E402
from app.domain.skills import models as _skill_models  # noqa: F401,E402

target_metadata = None


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live database connection."""

    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
    )

    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

