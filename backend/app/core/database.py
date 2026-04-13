"""Hinweisgebersystem – Async Database Engine & Session Factory.

Provides:
- ``async_engine``: SQLAlchemy async engine connected as ``app_user`` (non-superuser)
  so that PostgreSQL Row-Level Security policies are enforced.
- ``AsyncSessionFactory``: session maker bound to the engine.
- ``get_db()``: FastAPI dependency that yields a session with the RLS
  ``app.current_tenant_id`` set via ``SET LOCAL`` for each request.
- ``Base``: Declarative base for all ORM models.

RLS context flow:
1. The tenant resolver middleware determines the tenant ID from the request.
2. ``get_db()`` is injected as a dependency in route handlers.
3. Before the session is yielded the function executes
   ``SET LOCAL app.current_tenant_id = '<uuid>'`` so that all subsequent
   queries in the same transaction are filtered by the RLS policies.
4. ``SET LOCAL`` is scoped to the current transaction and automatically
   reset on commit / rollback — no cleanup needed.

Usage::

    from app.core.database import get_db
    from sqlalchemy.ext.asyncio import AsyncSession
    from fastapi import Depends

    @router.get("/items")
    async def list_items(db: AsyncSession = Depends(get_db)):
        result = await db.execute(select(Item))
        return result.scalars().all()
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = structlog.get_logger(__name__)


# ── Declarative base ──────────────────────────────────────────


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models.

    All models inherit from this class. Alembic's ``target_metadata``
    should be set to ``Base.metadata``.
    """


# ── Engine & session factory (initialised lazily) ─────────────

# These are populated by ``init_engine()`` during application startup
# (called from the lifespan context manager in main.py).
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str, **kwargs: object) -> None:
    """Create the async engine and session factory.

    Called once during application startup.  The ``database_url`` MUST
    point to the ``app_user`` role (non-superuser) so that RLS policies
    are enforced.

    Parameters
    ----------
    database_url:
        Async SQLAlchemy connection string
        (``postgresql+asyncpg://app_user:...@db:5432/hinweisgebersystem``).
    **kwargs:
        Extra keyword arguments forwarded to ``create_async_engine``
        (e.g. ``pool_size``, ``max_overflow``, ``pool_recycle``).
    """
    global _engine, _session_factory  # noqa: PLW0603

    _engine = create_async_engine(
        database_url,
        echo=False,
        pool_pre_ping=True,
        **kwargs,
    )
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    logger.info("database_engine_initialised", url=_mask_url(database_url))


async def dispose_engine() -> None:
    """Dispose of the async engine, closing all pooled connections.

    Called during application shutdown.
    """
    global _engine, _session_factory  # noqa: PLW0603

    if _engine is not None:
        await _engine.dispose()
        logger.info("database_engine_disposed")
    _engine = None
    _session_factory = None


def get_engine() -> AsyncEngine:
    """Return the current async engine, raising if not initialised."""
    if _engine is None:
        raise RuntimeError(
            "Database engine not initialised. Call init_engine() first."
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the current session factory, raising if not initialised."""
    if _session_factory is None:
        raise RuntimeError(
            "Session factory not initialised. Call init_engine() first."
        )
    return _session_factory


# ── Admin engine (bypasses RLS for cross-tenant lookups) ─────

# A second engine/session factory connected as the superuser role.
# Used exclusively for privileged cross-tenant lookups (e.g. OIDC
# user lookup by oidc_subject) where RLS cannot be scoped to a
# single tenant.

_admin_engine: AsyncEngine | None = None
_admin_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_admin_engine(admin_database_url: str, **kwargs: object) -> None:
    """Create the admin async engine and session factory.

    Called once during application startup.  The ``admin_database_url``
    MUST point to a superuser role that bypasses RLS.

    Parameters
    ----------
    admin_database_url:
        Async SQLAlchemy connection string for the admin/superuser role.
    **kwargs:
        Extra keyword arguments forwarded to ``create_async_engine``.
    """
    global _admin_engine, _admin_session_factory  # noqa: PLW0603

    _admin_engine = create_async_engine(
        admin_database_url,
        echo=False,
        pool_size=2,
        pool_pre_ping=True,
        **kwargs,
    )
    _admin_session_factory = async_sessionmaker(
        bind=_admin_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    logger.info("admin_database_engine_initialised", url=_mask_url(admin_database_url))


def get_admin_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the admin session factory, raising if not initialised."""
    if _admin_session_factory is None:
        raise RuntimeError(
            "Admin engine not initialised. Call init_admin_engine() first."
        )
    return _admin_session_factory


async def dispose_admin_engine() -> None:
    """Dispose of the admin async engine, closing all pooled connections.

    Called during application shutdown.
    """
    global _admin_engine, _admin_session_factory  # noqa: PLW0603

    if _admin_engine is not None:
        await _admin_engine.dispose()
        logger.info("admin_database_engine_disposed")
    _admin_engine = None
    _admin_session_factory = None


# ── RLS-aware session dependency ──────────────────────────────

# Tenant ID is set per-request by the tenant resolver middleware and
# stored in a contextvar / request state.  For now we accept it as an
# optional parameter; the middleware integration wires it up later.

async def get_db(tenant_id: UUID | None = None) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields an RLS-scoped database session.

    If ``tenant_id`` is provided the session executes
    ``SET LOCAL app.current_tenant_id`` so that PostgreSQL RLS policies
    filter all queries to the given tenant.  The ``SET LOCAL`` is scoped
    to the current transaction and requires no manual cleanup.

    Parameters
    ----------
    tenant_id:
        UUID of the current tenant.  ``None`` is allowed for
        unauthenticated / tenant-less endpoints (e.g. health check).
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            if tenant_id is not None:
                await session.execute(
                    text("SET LOCAL app.current_tenant_id = :tid"),
                    {"tid": str(tenant_id)},
                )
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Helpers ───────────────────────────────────────────────────


def _mask_url(url: str) -> str:
    """Mask the password portion of a database URL for safe logging."""
    # Quick and simple: replace between :// user: ... @ with asterisks
    try:
        prefix, rest = url.split("://", 1)
        if "@" in rest:
            credentials, host = rest.rsplit("@", 1)
            if ":" in credentials:
                user, _password = credentials.split(":", 1)
                return f"{prefix}://{user}:****@{host}"
        return url
    except Exception:
        return "****"
