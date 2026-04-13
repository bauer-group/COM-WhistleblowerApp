"""Hinweisgebersystem – Async Alembic Environment.

Configures Alembic to work with asyncpg via SQLAlchemy's async engine.
Migrations run as superuser (DATABASE_ADMIN_URL) to manage extensions,
roles, RLS policies, and DDL.  The application itself connects as
``app_user`` (non-superuser) to enforce Row-Level Security.

Key design decisions:
- ``run_async_migrations()`` wraps the synchronous Alembic API inside
  an async ``connection.run_sync()`` call so that asyncpg is used.
- ``target_metadata`` points to ``Base.metadata`` from
  ``app.core.database`` so that autogenerate can diff the ORM models.
- The database URL comes from the ``DATABASE_ADMIN_URL`` environment
  variable (falls back to ``sqlalchemy.url`` in alembic.ini for
  offline mode).

Usage::

    # Apply all pending migrations
    alembic upgrade head

    # Autogenerate a new migration from model changes
    alembic revision --autogenerate -m "add foo table"

    # Run migrations offline (SQL script output)
    alembic upgrade head --sql
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Import the ORM Base so target_metadata reflects all registered models.
# Models must be imported before this point — the models __init__.py
# re-exports them all, ensuring they are registered with Base.metadata.
from app.core.database import Base  # noqa: F401

# Alembic Config object — provides access to the .ini file values.
config = context.config

# Set up Python logging from the alembic.ini [loggers] section.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# MetaData object for autogenerate support.
target_metadata = Base.metadata


# ── URL resolution ───────────────────────────────────────────


def _get_database_url() -> str:
    """Resolve the database URL for migrations.

    Priority:
    1. ``DATABASE_ADMIN_URL`` environment variable (recommended)
    2. ``sqlalchemy.url`` from alembic.ini (fallback / offline)

    The admin URL uses superuser credentials so that migrations can
    CREATE EXTENSION, CREATE ROLE, ALTER TABLE … ENABLE ROW LEVEL
    SECURITY, and other privileged DDL operations.
    """
    url = os.environ.get("DATABASE_ADMIN_URL", "")
    if url:
        return url
    # Fall back to alembic.ini (useful for offline / SQL-generation mode)
    return config.get_main_option("sqlalchemy.url", "")


# ── Offline migrations (SQL script output) ───────────────────


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This emits SQL statements to stdout instead of connecting to the
    database.  Useful for generating migration SQL scripts for review
    or for applying via ``psql``.

    Calls to ``context.execute()`` emit the given string to the
    script output.
    """
    url = _get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ── Online (async) migrations ────────────────────────────────


def do_run_migrations(connection: Connection) -> None:
    """Synchronous migration runner called inside ``run_sync()``.

    This is the callback passed to ``connection.run_sync()`` — it
    configures Alembic's migration context with the live connection
    and then executes all pending migrations.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        # Do not auto-generate RLS policies; use raw SQL via op.execute()
        include_object=lambda obj, name, type_, reflected, compare_to: True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations using an async engine (asyncpg).

    Creates a disposable async engine from the configuration, obtains
    an async connection, and delegates to the synchronous
    ``do_run_migrations()`` via ``run_sync()``.
    """
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode with an async engine.

    Delegates to ``run_async_migrations()`` which handles the
    asyncpg connection lifecycle.
    """
    asyncio.run(run_async_migrations())


# ── Entry point ──────────────────────────────────────────────

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
